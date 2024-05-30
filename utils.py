from datetime import datetime, timedelta, time as _time
import re
from abc import ABC, abstractmethod

from holo.__typing import (
    Sequence, Iterable, Literal, TypeVar, Union, Self,
    TypedDict, NotRequired, TYPE_CHECKING, JsonTypeAlias,
    get_args, cast,
)
from holo.protocols import _T
from holo.prettyFormats import (
    DEFAULT_COMPACT_RULES, PrettyPrint_CompactArgs,
)

if TYPE_CHECKING:
    from model import _TimeID


DATETIME_PRETTY_FORMAT: str = "%a %d %b %Y %Hh%M"
DATE_ONLY_PRETTY_FORMAT: str = "%a %d %b %Y"
TIME_ONLY_PRETTY_FORMAT: str = "%Hh%M:%S"
DATETIME_COMPACT_FORMAT: str = "%d/%m/%Y %Hh%M"
DATETIME_COMPACT_DATE_ONLY_FORMAT: str = "%d/%m/%Y"

DATETIME_FORMAT: str = "%d/%m/%Y-%Hh%M:%S"

def _createParseTimeCaptureGroup(grpName:str, names:"Sequence[str]",
                                 type_:"Literal['float', 'int']"):
    valueFormat = (r"\d+" if type_ == "int" else r"\d*\.?\d+")
    return rf"(?:(?P<{grpName}>{valueFormat})[ ]*(?:{'|'.join(names)}))?"

PARSE_TIME_PATTERN = re.compile(
    r"^[ ]*" + _createParseTimeCaptureGroup("days", ("d", "day", "days"), 'int') \
    + r"[ ]*" + _createParseTimeCaptureGroup("hours", ("h", "hr", "hour", "hours"), 'int') \
    + r"[ ]*" + _createParseTimeCaptureGroup("minutes", ("m", "min", "minute", "minutes"), 'int') \
    + r"[ ]*" + _createParseTimeCaptureGroup("seconds", ("s", "sec", "second", "seconds"), 'float') + r"[ ]*$"
)


_PeriodeColumn = Literal["start date", "end date", "duration", "activity"]
_PeriodeField = Literal["startTime", "endTime", "duration", "activity", "comments"]
_PeriodeFields_sortable = Literal["startTime", "endTime", "duration", "activity"]
_ConfigField = Literal["name", "description", "targetedTime", "targetedTimeFrame"]
_PeriodeColumn_TO_PeriodeField: "dict[_PeriodeColumn, _PeriodeFields_sortable]" = {
    "start date": "startTime", "end date": "endTime", 
    "duration": "duration", "activity": "activity",
}
_TimeFrame_literals = Literal["year", "month", "week", "day"]
_TimeFrame = Union[_TimeFrame_literals, "_TimeID"]
_CommentsMerge = Literal['self', 'other', 'None']
_T_TimeID = TypeVar("_T_TimeID", "_TimeID", None)
_UpdatedTarget = Literal["periodes", "clockin", "activity", "config", "selectedTime", "selectedTimeFrame"]
_UpdatedALLTarget: "set[_UpdatedTarget]" = set(get_args(_UpdatedTarget))
_SaveResponse = Literal['done', 'canceled']
_ActivityColumn = Literal["name", "number of time used", "total cumulated duration"]
_SubActionType = Literal['added', 'removed']
_ExportTableColumn = Literal["name"]

def prettyTimedelta(seconds:"float|timedelta", useDays:bool=False)->str:
    if isinstance(seconds, timedelta):
        seconds = seconds.total_seconds()
    if seconds < 0.0:
        raise ValueError(f"the given time: {seconds} seconds must be a positive number")
    elif seconds < 60: # => less than a minute
        return f"{round(seconds, 1)} seconds"
    elif seconds < 3600: # => less than an hour
        return f"{int(seconds // 60)} minutes"
    else: # => more than an hour
        durationHours, durationMinutes = divmod(int(seconds // 60), 60)
        if useDays is True:
            durationDays, durationHours = divmod(durationHours, 24)
        else: durationDays = 0
        # => use days
        durationTexts: list[str] = []
        if durationDays != 0: 
            durationTexts.append(f"{durationDays}day" + ("s" if durationDays else ""))
        if durationHours != 0:
            durationTexts.append(f"{durationHours}hour" + ("s" if durationHours else ""))
        if durationMinutes != 0:
            durationTexts.append(f"{durationMinutes}minute" + ("s" if durationMinutes else ""))
        return " ".join(durationTexts)


def prettyDatetime(t:datetime, format:"Literal['full', 'auto', 'date', 'time', 'compact']")->str:
    if format == "full": return t.strftime(DATETIME_PRETTY_FORMAT)
    elif format == "auto":
        if t.time() == _time.min: # => 0h0m0s
            return t.strftime(DATE_ONLY_PRETTY_FORMAT)
        return t.strftime(DATETIME_PRETTY_FORMAT)
    elif format == "date": return t.strftime(DATE_ONLY_PRETTY_FORMAT)
    elif format == "time": return t.strftime(TIME_ONLY_PRETTY_FORMAT)
    elif format == "compact": 
        if t.time() == _time.min: # => 0h0m0s
            return t.strftime(DATETIME_COMPACT_DATE_ONLY_FORMAT)
        return t.strftime(DATETIME_COMPACT_FORMAT)
    else: raise ValueError(f"invalide format: {format}")
    

def datetimeToText(t:datetime)->str:
    return t.strftime(DATETIME_FORMAT)

def datetimeFromText(text:str)->datetime:
    return datetime.strptime(text, DATETIME_FORMAT)

def timedeltaFromText(text:str)->timedelta:
    m = PARSE_TIME_PATTERN.match(text)
    if m is None: raise ValueError(f"the deltatime text: {repr(text)} don't match the regex pattern: {PARSE_TIME_PATTERN.pattern}")
    return timedelta(**{key: float(val) for key, val in m.groupdict().items() if val is not None})

def prettyTimeFrame(timeframe:"_TimeFrame")->str:
    if isinstance(timeframe, str):
        # => literal
        return timeframe
    # => _TimeID
    return timeframe.prettyTimeFrameText()

def substractSet(s:"set[str]", substract:"Iterable[str]")->"set[str]":
    """remove in place the elements of `substract`, and retun the set `s`"""
    for elt in substract: s.remove(elt)
    return s

def substractList(l:"Iterable[str]", substract:"set[str]")->"list[str]":
    """remove in place the elements of `substract`, and retun the set `s`"""
    return [elt for elt in l if elt not in substract]
    
def isEmptySubActions(subActions:"list[tuple[_SubActionType, list[_T]]]")->bool:
    """`subActions`: from first actions done to the last done (they must not be empty)"""
    if len(subActions) == 0:
            return True # => no sub action
    # => self has some sub action
    # test if they cancel each other
    elementsState: "dict[_T, _SubActionType]" = {}
    """the elements inside are the ones that have been modified"""
    for (actionType, subElements) in reversed(subActions):
        for element in subElements:
            if element not in elementsState:
                elementsState[element] = actionType
                continue
            # => activity alredy listed
            currentActionType: "_SubActionType" = elementsState[element]
            assert currentActionType != actionType, \
                ValueError(f"invalide subActions, doing twice the action: {currentActionType} on {element}")
            # => actions cancel
            elementsState.pop(element)
            continue
    # activityState is empty <=> all sub actions got canceled 
    #   <=> did nothing <=> is empty
    return (len(elementsState) == 0)


class TrustError(Exception):
    def __init__(self, source:object) -> None:
        super().__init__(f"{source.__class__.__name__} is having trust issue, he thought he could have trusted you :'/ ")
    

class Jsonable(ABC):
    __slots__ = ()
    @classmethod
    @abstractmethod
    def fromJson(cls, datas:"JsonTypeAlias")->"Self": ...
    @abstractmethod
    def toJson(self)->"JsonTypeAlias": ...

JSON_SEMI_COMPACT_ARGS = \
    PrettyPrint_CompactArgs(
        compactSmaller=2, compactLarger=False,
        keepReccursiveCompact=False,
        compactRules=DEFAULT_COMPACT_RULES)