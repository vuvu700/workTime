from pathlib import Path

FILE_ENCODING = "utf-8"

DIRECTORY = Path(__file__).parent

LOGGS_FILE_PATH = DIRECTORY.joinpath("currentSessionLogs.log")

DATAS_DIRECTORY = DIRECTORY.joinpath("datas")
if DATAS_DIRECTORY.exists() is False:
    DATAS_DIRECTORY.mkdir(parents=True, exist_ok=True)

SCHEDULES_DIRECTORY = DIRECTORY.joinpath("schedules")
if SCHEDULES_DIRECTORY.exists() is False:
    SCHEDULES_DIRECTORY.mkdir(parents=True, exist_ok=True)

ASSETS_DIRECTORY = DIRECTORY.joinpath("assets")
ICON_PATH = ASSETS_DIRECTORY.joinpath("appIcon.ico")
assert ICON_PATH.exists()

assert DATAS_DIRECTORY.exists()

