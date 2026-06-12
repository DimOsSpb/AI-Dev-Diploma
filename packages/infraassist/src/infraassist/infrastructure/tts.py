from pathlib import Path
from subprocess import CalledProcessError, run  # noqa: S404

from infraassist.infrastructure.config import Settings


class RobustTTSClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def synthesize(self, text: str, output: str) -> str | None:
        try:
            # current_dir = Path.cwd()
            # print(f"Текущий каталог: {current_dir}")
            run(  # noqa: S603
                [
                    str(self.settings.piper_bin),
                    "-q",
                    "--model",
                    str(self.settings.tts_model_path),
                    "--output_file",
                    output,
                ],
                input=text,
                text=True,
                check=True,
            )
        except CalledProcessError:
            return ""

        return output if Path(output).exists() else None

    def play(self, audio_path: str) -> None:
        run(  # noqa: S603
            ["aplay", "-q", audio_path],  # noqa: S607
            check=False,
        )
