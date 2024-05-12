from pathlib import Path

DIRECTORY = Path(__file__).parent

LOGGS_FILE_PATH = DIRECTORY.joinpath("currentSessionLogs.log")

DATAS_DIRECTORY = DIRECTORY.joinpath("datas")
if DATAS_DIRECTORY.exists() is False:
    DATAS_DIRECTORY.mkdir(parents=True, exist_ok=True)

ASSETS_DIRECTORY = DIRECTORY.joinpath("assets")
ICON_PATH = ASSETS_DIRECTORY.joinpath("appIcon.ico")


assert DATAS_DIRECTORY.exists()

