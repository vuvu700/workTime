from datetime import datetime

from holo.__typing import Any as _Any, TypedDict

from utils import (
    datetimeFromText, datetimeToText,
    _TimeFrame_literals,
)


def hasRequiredKeys(datas:"dict[str, _Any]", requiredKeys:"frozenset[str]")->bool:
    return requiredKeys.issubset(datas.keys())

def datetimeToJson(t: datetime)->"AsJson_Datetime":
    return AsJson_Datetime(cls=datetime.__name__, value=datetimeToText(t))
def datetimeFromJson(datas:"AsJson_Datetime")->"datetime":
    assert datas["cls"] == datetime.__name__
    assert isinstance(datas["value"], str)
    return datetimeFromText(datas["value"])


#########################################################


class AsJson_FullDatas(TypedDict):
    cls: "str"
    periodes: "list[AsJson_Periode]"
    registeredActivities: "list[AsJson_Activity]"
    configuration: "AsJson_Configuration"
    selectedTime: "AsJson_Datetime"
    selectedTimeFrame: "_TimeFrame_literals|AsJson_Periode"
    clockinTime: "None|AsJson_Datetime"


class AsJson_Configuration(TypedDict):
    cls: str
    name: str
    description: str
    targetedTimePerPeriode: "AsJson_TimeTarget"
    accumulateDeltaToTarget: bool

class AsJson_Periode(TypedDict):
    cls: str
    startTime: "AsJson_Datetime"
    endTime: "AsJson_Datetime"
    activity: "AsJson_Activity"
    comments: str

class AsJson_Activity(TypedDict):
    cls: str
    activity: "None|str"

class AsJson_Datetime(TypedDict):
    cls: str
    value: str

class AsJson_PrettyTimedelta(TypedDict):
    cls: str
    seconds: float

class AsJson_TimeTarget(TypedDict):
    cls: str
    targetedTime: "AsJson_PrettyTimedelta"
    timeFrame: "_TimeFrame_literals|AsJson_Periode"
