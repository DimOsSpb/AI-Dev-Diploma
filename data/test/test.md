# Инструкция: Администрирование Pods в Kubernetes

Быстрое руководство по управлению, проверке состояния и отладке подов с помощью `kubectl`.

## 1. Просмотр состояния (Inspection)

* `kubectl get pods` — список всех подов в текущем пространстве имен (namespace).
* `kubectl get pods -n <namespace>` — список подов в конкретном namespace.
* `kubectl get pod <pod-name> -o yaml` — просмотр полной конфигурации пода в формате YAML.
* `kubectl describe pod <pod-name>` — подробная информация о поде (события, статус контейнеров, причины ошибок).

## 2. Отладка и логирование (Debugging)

* `kubectl logs <pod-name>` — просмотр логов пода (контейнера).
* `kubectl logs <pod-name> -c <container-name>` — логи конкретного контейнера (если в поде их несколько).
* `kubectl logs -f <pod-name>` — просмотр логов в реальном времени (стриминг).
* `kubectl exec -it <pod-name> -- sh` — подключение к терминалу внутри контейнера (вместо `sh` можно использовать `bash`).

## 3. Управление жизненным циклом (Lifecycle)

* `kubectl delete pod <pod-name>` — удаление (перезапуск) конкретного пода.
* `kubectl apply -f <file-name>.yaml` — создание или обновление пода из файла конфигурации.
* `kubectl replace --force -f <file-name>.yaml` — принудительное пересоздание пода.

## 4. Перенаправление портов (Порт-форвардинг)

* `kubectl port-forward <pod-name> <local-port>:<pod-port>` — проброс порта с локальной машины в под для быстрого тестирования (например, `8080:80`).
