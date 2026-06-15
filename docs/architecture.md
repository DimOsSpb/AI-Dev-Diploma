# Диаграмма

```mermaid
flowchart TB

    classDef layerStyle stroke-width:1px, stroke:#ccc, fill:#fafafa
    classDef aquaStyle stroke-width:1px, stroke:#46EDC8, fill:#DEFFF8, color:#378E7A
    

    subgraph LAY_GW ["01. GATEWAY LAYER"]
        direction TB
        GW["`**API Gateway (Nginx)**
        Auth • Rate Limit • SSL`"]
    end
    style LAY_GW layerStyle

    subgraph LAY_SRV ["02. SERVICE LAYER"]
        direction TB
        SRV["`**Core Service (FastAPI)**
        Application Logic`"]
        
        subgraph COMP ["Внутренние компоненты"]
            direction LR
            CACHE["Cache"]
            STAT["Stat"]
            LOG["Log"]
        end
        SRV ~~~ COMP
    end
    style LAY_SRV layerStyle

    subgraph LAY_LLM ["03. LLM LAYER"]
        direction TB

        subgraph CB ["Circuit Breaker ( Retry & backoff - fail_max=5, timeout=60s )"]
            direction TB

            subgraph RB [" "]
                direction LR
                PR1["`**1. Primary**
                ChatGPT API`"]
                
                PR2["`**2. Secondary**
                OpenRouter API`"]
                
                PR3["`**3. Local**
                Ollama (Self-hosted)`"]

                PR4["Сервис временно недоступен"]
                
                PR1 -.->|CB| PR2 -.->|CB| PR3 -.-> |Error| PR4 
                
            end
            style RB fill:none,stroke:none 
            
        end
        CB ~~~ RB
    end
    style LAY_LLM layerStyle

    subgraph LAY_DATA ["04. DATA LAYER"]
        direction LR
        DATA["Redis / PostgreSQL / Qdrant"]
    end
    style LAY_DATA layerStyle

    %% --- ПОТОК ---
    USER["`**= Оператор =**
    Telegram / Web UI`"]

    USER <==>|HTTP / WebSockets| GW
    GW <==> SRV

    SRV -->|Классификация запроса| CB
    CACHE <--> DATA
    STAT & LOG --> DATA

    SRV ==>|Запрос к LLM| CB

    PR1 & PR2 & PR3 -.->|Успешный ответ| SRV
    PR4 -. Проблема .-> SRV
    USER ~~~ LAY_GW
    LAY_GW ~~~ LAY_SRV
    LAY_SRV ~~~ LAY_LLM
    LAY_SRV ~~~ LAY_DATA
```

---
# ADR (Architecture Decision Record)

## ADR-001: Выбор паттерна взаимодействия

**Status:**  

Accepted (2026-06-14)  

**Context.**  

Проект — Интеллектуальный ассистент мониторинга и диагностики ИТ-инфраструктуры. Ожидаемая
нагрузка для крупной инфраструктуры (ИТ-департамент размером примерно в 150–300 человек) — для 50 активных операторов 90 сообщений/мин в пике, примерно в среднем 800 токенов на один запрос.
(0.5–8 секунд генерации), бюджет $40/мес.  

**Decision.**  

Выбран **Queue-based architecture**. Инженер вводит команду/запрос в CLI или Web. Бэкенд мгновенно принимает запрос, инженер видит статус тикета, ответ приходит ассинхронно.  

**Consequences.**

- Плюсы: Защита от пиковых нагрузок (Управление RPM) - сервер не упадет с ошибкой 504 Gateway Timeout.
- Минусы: Реализация архитектурно сложней.  

**Alternatives.**

- Request-Response & Streaming — отвергнут, ИИ-агенту нужно опрашивать разные системы (K8s, Prometheus, логи, базы данных), классический синхронный запрос быстро «упадет» по таймауту. Очередь решает эту проблему
- Fan-out - не наш случай, у нас короткий запрос/задача.

## ADR-002: Стратегия fault tolerance

**Decision.**  

- Primary — OpenAI gpt-4(5)-mini (ориентируемся на цена/качество).
- Fallback — Anthropic claude-sonnet-4-6. 
- Tertiary — Ollama qwen3:32b (локально, на случай полного отказа облаков).  
- Circuit Breaker — `tenacity`, fail_max=5, timeout=60s, **по одному на
провайдера**. Cache-Aside в Redis если допустимо, TTL по типу ответа, ключ —
`sha256(model + messages + temperature)`.  

**Consequences.**  

Доступность сервиса гарантируется даже при одновременном
падении OpenAI + Anthropic (Ollama держит UX «работаем в ограниченном режиме»).
Стоимость: дополнительные $5/мес за минимальный Anthropic-трафик + затраты на
self-hosted Ollama на VPS / On-premises.

# Потенциальные точки отказа

по одной на
слой. Для каждого слоя указывается: что произойдёт при его выпадении, какой паттерн
смягчает удар, как сервис деградирует (graceful degradation). Например: «LLM — все
провайдеры лежат → fallback на template-ответ из FAQ

1. GATEWAY LAYER
- Превышен Rate limit
  - Вводим ограничение на количество запросов в минуту
  - Блокируем тех кто дедосит
- Полное падение - сервис станет недоступен полностью
  - Важно иметь отказоустойчивое решение
2. SERVICE LAYER
- Не хватает ресурсов (память, CPU...)
  - Мониторим потребление, зарание решаем проблему
- Полное падение - сервис станет недоступен полностью
  - На уровне 1 отвечать - например "Сервис временно недоступен, повторите запрос позже"
3. LLM LAYER
- Недоступность провайдера(ов) и даже локального LLM
  - Ищем похожие запросы в кеш/faq - если есть отдаем. Если нет - даем приемлимый ответ
4. DATA LAYER
- Не хватает ресурсов (память, CPU...)
  - Мониторим потребление, зарание решаем проблему
- Полное падение - сервис потеряет доступ к stats/cache... Это не смертельно, возможно но увеличит скорость ответтов и вункциональность SERVICE LAYER
  - Важно иметь отказоустойчивое решение
