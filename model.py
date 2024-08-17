import os.path
from io import BufferedReader
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from pathlib import Path
import json
import locale

from holo.__typing import (
    Literal, Iterable, Sequence, Union, Iterator, TextIO,
    Generic, PartialyFinalClass, FinalClass, Self,
    assertIsinstance, overload, override, get_args, cast,
    DefaultDict, Any, 
)
from holo.protocols import _T
from holo.prettyFormats import (
    prettyPrint, prettyPrintToJSON, 
    PrettyfyClass, _ObjectRepr,
)
from holo.linkedObjects import (
    SkipList, History as _HistoryBackend, NoHistoryError, )

from utils import (
    TrustError, Jsonable,
    _UpdatedTarget, _PeriodeFields_sortable,
    JSON_SEMI_COMPACT_ARGS, _TimeFrame, _TimeFrame_literals, _SubActionType,
    _T_TimeID, _ConfigField, _PeriodeField, _CommentsMerge,
    datetimeFromText, datetimeToText, prettyDatetime, prettyTimedelta, 
    timedeltaFromText, prettyTimeFrame, isEmptySubActions,
)
from saveFormat import (
    AsJson_Datetime, AsJson_Activity, AsJson_PrettyTimedelta,
    AsJson_Periode, AsJson_FullDatas, AsJson_Configuration,
    AsJson_TimeTarget,
    datetimeToJson, datetimeFromJson,
)


### all datetime are in local time
locale.setlocale(locale.LC_TIME, "fr_FR")

EPSILON_DURATION: timedelta = timedelta.resolution


def timeFrameFromText(text:str)->"_TimeFrame":
    """either a `_TimeFrame_literals` is given\n
    or a "startTime->endTime" is given"""
    if text in get_args(_TimeFrame_literals):
        return cast(_TimeFrame_literals, text)
    # => convert to a _TimeID
    try: startTime, endTime = text.split("->", maxsplit=1)
    except ValueError: raise ValueError(f"can't convert {repr(text)} to _TimeFrame")
    return _TimeID.fromText(startTime=startTime, endTime=endTime)

def timeFrameToText(timeFrame:"_TimeFrame")->str:
    """convert a timeframe to a text that can be decoded with timeFrameFromText"""
    if isinstance(timeFrame, str):
        return timeFrame
    # => timeFrame is a _TimeID
    return f"{datetimeToText(timeFrame.startTime)}->{datetimeToText(timeFrame.endTime)}"

def timeFrameToJson(timeframe:"_TimeFrame")->"_TimeFrame_literals|AsJson_Periode":
    if isinstance(timeframe, str):
        return timeframe
    # to be able to select the right subclass of Periode to read from json
    return timeframe.asTimeID().toJson()

def timeFrameFromJson(data:"_TimeFrame_literals|AsJson_Periode")->"_TimeFrame":
    if isinstance(data, str):
        return data
    return _TimeID.fromJson(data)

def getRealPath(file:"TextIO|BufferedReader")->"Path":
    return Path(os.path.realpath(file.name))

#########################################################


class FullDatas(PartialyFinalClass, PrettyfyClass, Jsonable):
    __slots__ = ("__allPeriodes", "__selectedTime", "__selectedTimeFrame", "__clockinTime",
                 "__registeredActivities", "__configuration", "__history", "__trustMode", 
                 "__saveFilePath", "__lastSave_histNodeID", )
    __finals__ = {"__allPeriodes", "__registeredActivities", "__history", "__configuration"}
    __prettyAttrs__ = list(__slots__)
    
    def __init__(self, allPeriodes:"None|Iterable[Periode]", configuration:"Configuration", 
                 selectedTime:"datetime", selectedTimeFrame:"_TimeFrame", 
                 clockinTime:"datetime|None", registeredActivities:"Iterable[Activity]|None",
                 fromSaveFile:"Path|None") -> None:
        self.__allPeriodes: "PeriodesStorage[None]" = \
            PeriodesStorage(timeID=None, periodes=None, histActions=None)
        self.__configuration: "Configuration" = configuration
        self.__selectedTime: "datetime" = selectedTime
        self.__selectedTimeFrame: "_TimeFrame" = selectedTimeFrame
        self.__registeredActivities: "set[Activity]" = set()
        if registeredActivities is not None: 
            self.__registeredActivities.update(registeredActivities)
        self.__clockinTime: "datetime|None" = clockinTime
        self.__history: "History" = History()
        self.__trustMode: bool = False
        self.__saveFilePath: "Path|None" = fromSaveFile
        """allow to use the trused methodes when True"""
        # add the perioes
        if allPeriodes is not None:
            self.extends(list(allPeriodes))
        # set the id here when the list is fully inited from the datas
        self.__history.clearHistory()
        self.__lastSave_histNodeID: int = self.__history.getCurrentNodeID()
    
    ### history public ops
    
    def revert(self)->"set[_UpdatedTarget]":
        """try to revert the last action, might raise a NoHistoryError"""
        self.__trustMode = True
        try: return self.__history.revertOne(self)
        finally: self.__trustMode = False
    
    def redo(self)->"set[_UpdatedTarget]":
        """try to redo the last action, might raise a NoHistoryError"""
        self.__trustMode = True
        try: return self.__history.redoOne(self)
        finally: self.__trustMode = False
    
    ### create / save the datas
    
    @classmethod
    def create_empty(cls) -> "FullDatas":
        """create empty datas holder"""
        datas = FullDatas(
            allPeriodes=None, configuration=Configuration.createEmpty(), 
            selectedTime=datetime.now(), selectedTimeFrame="week",
            clockinTime=None, registeredActivities={Activity(None)}, fromSaveFile=None) 
        return datas
    
    def toJson(self)->"AsJson_FullDatas":
        clockinTime: "AsJson_Datetime|None" = \
            (None if self.__clockinTime is None else datetimeToJson(self.__clockinTime))
        return AsJson_FullDatas(
            cls=self.__class__.__name__,
            periodes=[periode.toJson() for periode in self.__allPeriodes],
            registeredActivities= \
                [activity.toJson() for activity in self.__registeredActivities],
            configuration=self.__configuration.toJson(),
            selectedTime=datetimeToJson(self.__selectedTime),
            selectedTimeFrame=timeFrameToJson(self.__selectedTimeFrame),
            clockinTime=clockinTime)
    
    @classmethod
    def fromJson(cls, datas:"AsJson_FullDatas", *, _fromFile:"Path|None")->"Self":
        assert datas["cls"] == cls.__name__
        fullDatas = FullDatas.__new__(cls)
        FullDatas.__init__(
            self=fullDatas, 
            allPeriodes=[Periode.fromJson(subData) for subData in datas["periodes"]],
            registeredActivities= \
                [Activity.fromJson(subData) for subData in datas["registeredActivities"]],
            configuration=Configuration.fromJson(datas["configuration"]),
            clockinTime=(None if datas["clockinTime"] is None 
                         else datetimeFromJson(datas["clockinTime"])),
            selectedTime=datetimeFromJson(datas["selectedTime"]),
            selectedTimeFrame=timeFrameFromJson(datas["selectedTimeFrame"]),
            fromSaveFile=_fromFile)
        return fullDatas
    
    @classmethod
    def fromFile(cls, file:BufferedReader)->"FullDatas":
        return cls.fromJson(json.load(file), _fromFile=getRealPath(file))
    
    def saveToFile(self, file:TextIO, compact:bool=False)->None:
        """save the datas to a file in the json format"""
        prettyPrintToJSON(
            self.toJson(), stream=file, end=None,
            indentSequence=" "*2, 
            compact=(compact or JSON_SEMI_COMPACT_ARGS))
        self.__saveFilePath = getRealPath(file)
        self.__lastSave_histNodeID = self.__history.getCurrentNodeID()
    
    def exportPeriodes(self, selectedInterval:"_TimeID|None", selectedActivities:"set[Activity]", 
                       useConfig:"Literal['self', 'export']"='export')->"FullDatas":
        """export all the periodes in the `selectedInterval` (None -> all) that with an activity in `selectedActivities`\n
        the exported """
        periodesToExport: "list[Periode]" = []
        if selectedInterval is None:
            selectedInterval = _TimeID(datetime.min, datetime.max)
        # get all the periodes to export
        for periode in self.__allPeriodes.getSubset(selectedInterval):
            if periode.activity in selectedActivities:
                periodesToExport.append(periode)
        # create the config for the exported datas
        exportConfig: Configuration
        if useConfig == "self":
            exportConfig = self.__configuration.copy()
        elif useConfig == "export":
            exportConfig = Configuration(
                name=f"exported datas from {self.__configuration.name}", 
                description="(the description was generated at export)" \
                    f"exported the periodes {selectedInterval.prettyTimeFrameText()} "\
                    f"with pe activities: {selectedActivities} (use the same time target and accum)", 
                targetPerPeriode=self.__configuration.getTimeTarget())
        else: raise ValueError(f"invalide `useConfig` value: {repr(useConfig)}")
        # create the new datas with the extracted periodes
        return FullDatas(
            allPeriodes=periodesToExport, configuration=exportConfig, 
            selectedTime=self.__selectedTime, selectedTimeFrame=self.__selectedTimeFrame,
            clockinTime=None, registeredActivities=selectedActivities, 
            fromSaveFile=None)
        
    
    ### public getters
    
    def isSaved(self)->bool:
        """tell whether the datas are the same as what was last saved"""
        return (self.__history.getCurrentNodeID() == self.__lastSave_histNodeID)
    
    def getSavePath(self)->"Path|None":
        return self.__saveFilePath
    
    def getSelectedTime(self)->datetime:
        return self.__selectedTime

    def getSelectedTimeFrame(self)->"_TimeFrame":
        return self.__selectedTimeFrame
    
    def get_TimeID(self, selectedTime:"None|datetime", selectedTimeFrame:"None|_TimeFrame")->"_TimeID":
        """gets you the _TimeID of the given `selectedTime` and `selectedTimeFrame` (None -> use the one from self)"""
        if selectedTime is None: selectedTime = self.__selectedTime
        if selectedTimeFrame is None: selectedTimeFrame = self.__selectedTimeFrame
        return _TimeID.getTimeID(selectedTime, selectedTimeFrame)
    
    def getSubTimeFrame(self, timeFrame:"_TimeFrame|None")->"_TimeFrame":
        """return the subdivision of the given `timeFrame`\n
        custom timeFrames (as _TimeID) and 'day' will retturn itself"""
        if timeFrame is None:
            timeFrame = self.__selectedTimeFrame
        if timeFrame == "year": return "month"
        elif timeFrame == "month": return "week"
        elif timeFrame == "week": return "day"
        elif timeFrame == "day": return "day"
        elif isinstance(timeFrame, _TimeID): return timeFrame
        else: raise ValueError(f"invalide timeFrame: {timeFrame}")
    
    def getPeriodes(self, selectedTime:"None|datetime", selectedTimeFrame:"None|_TimeFrame")->"PeriodesStorage[_TimeID]":
        """get all the periodes in the given"""
        return self.__allPeriodes.getSubset(self.get_TimeID(selectedTime, selectedTimeFrame))

    def getConfigText(self, field:"_ConfigField")->str:
        """get the text of the field of the config for the edit\n
        this is not meant for pretty texts"""
        return self.__configuration.getFieldValueAsText(field)

    def getTimeTarget(self)->"TimeTarget":
        return self.__configuration.getTimeTarget()

    def getRegisteredActivites(self)->"list[Activity]":
        """return the activities sorted by nb of use (most used -> least used)"""
        return sorted(self.__registeredActivities, reverse=True,
                      key=self.__allPeriodes.getActivitiesUsageCount)
    
    def getActivitiesUsages(self)->"dict[Activity, int]":
        """return all the registered activities and the number of periodes that use them"""
        return {activity: self.__allPeriodes.getActivitiesUsageCount(activity)
                for activity in self.__registeredActivities}
    
    def getAllPeriodesInterval(self)->"_TimeID|None":
        """return the precise interval that holds all the periodes, or None if it has no periodes"""
        return self.__allPeriodes.getAllPeriodesInterval()
    
    ### selected time
    
    def __gotoInternal(self, gotoTime:datetime)->"set[_UpdatedTarget]":
        oldSelectedTime: datetime = self.__selectedTime
        oldTimeID: "_TimeID" = self.get_TimeID(None, None)
        self.__selectedTime = gotoTime
        if self.__selectedTime in oldTimeID:
            # => didin't changed the periodes interval
            return set()
        self.__history.addAction(HistorySelectedTime(
            oldTime=oldSelectedTime, newTime=self.__selectedTime))
        return {"selectedTime"}
    
    def goToPrev_TimeFrame(self)->"set[_UpdatedTarget]":
        """move the selected time to the previous interval"""
        return self.__gotoInternal(
            self.get_TimeID(None, None).prev().lastTime)
    
    def goToNext_TimeFrame(self)->"set[_UpdatedTarget]":
        """move the selected time to the next interval"""
        return self.__gotoInternal(
            self.get_TimeID(None, None).next().lastTime)
    
    def goToLast_TimeFrame(self)->"set[_UpdatedTarget]":
        """move the selected time to the last interval containing some periodes"""
        allPeriodesInterval: "_TimeID|None" = self.getAllPeriodesInterval()
        if allPeriodesInterval is None: # => self has no periode
            return set() # => don't move =>did nothing
        return self.__gotoInternal(allPeriodesInterval.lastTime)
    
    def goToFirst_TimeFrame(self)->"set[_UpdatedTarget]":
        """move the selected time to the first interval containing some periodes"""
        allPeriodesInterval: "_TimeID|None" = self.getAllPeriodesInterval()
        if allPeriodesInterval is None: # => self has no periode
            return set() # => don't move =>did nothing
        return self.__gotoInternal(allPeriodesInterval.startTime)
        

    def goToNow(self)->"set[_UpdatedTarget]":
        """move the selected timeFrame to now\n
        return whether it has changed the selected timeID"""
        return self.__gotoInternal(datetime.now())
    
    def selectTimeFrame(self, timeframe:"_TimeFrame")->"set[_UpdatedTarget]":
        if self.__selectedTimeFrame == timeframe:
            # => same timeframe
            return set() # no changes
        oldTimeFrame: "_TimeFrame" = self.__selectedTimeFrame
        self.__selectedTimeFrame = timeframe
        self.__history.addAction(HistorySelectedTimeFrame(
            newSelection=timeframe, oldSelection=oldTimeFrame))
        return {"selectedTimeFrame"}
    
    ### clockin related methodes
    # publics

    def getClockinTime(self)->"datetime|None":
        return self.__clockinTime

    def isClockedIn(self)->bool:
        return self.__clockinTime is not None

    def clockin(self)->None:
        if self.isClockedIn():
            raise ValueError("alredy clocked in, can't clock in twice")
        self.__clockinTime = datetime.now()
        self.__history.addAction(HistoryClockingAction(
            clockinValue=self.__clockinTime, action="clockedin"))
    
    def clockout(self)->"Periode":
        clockedPeriode: "Periode|None" = \
            self.__getPeridodeSinceClockedIn()
        if clockedPeriode is None:
            raise ValueError("not clocked in, can't clock out")
        self.unClockin()
        return clockedPeriode
    
    def unClockin(self)->None:
        if self.__clockinTime is None:
            raise ValueError("not clocked in, can't un clock in")
        self.__history.addAction(HistoryClockingAction(
            clockinValue=self.__clockinTime, action="unclockedin"))
        self.__clockinTime = None

    # privates

    def __getPeridodeSinceClockedIn(self)->"Periode|None":
        if self.__clockinTime is None:
            return None
        return Periode(startTime=self.__clockinTime, endTime=datetime.now(), 
                       activity=None, comments=None) # will be filled later
    def __getTimeClockedIn_perTimeFrame(self, timeFrame:"_TimeFrame")->"dict[_TimeID, timedelta]":
        periodesClockedIn = self.__getPeridodeSinceClockedIn()
        if periodesClockedIn is None: return {} # => not clocked in
        else: # => has clocked in
            return {timeID: periode.duration for timeID, periode in
                        periodesClockedIn.splitPer_TimeFrame(timeFrame).items()}

    ### to compute the stats

    def timeSinceClockedIn(self, *, default:"_T"=None)->"timedelta|_T":
        """the time since clocked in, if not clocked in retun `default`"""
        if self.__clockinTime is None:
            return default # => not clocked in
        return datetime.now() - self.__clockinTime

    def cumulatedDuration(self, selection:"_TimeID|Literal['all']")->timedelta:
        """return the cumulated time plus the time since clockedin if in the selected `weekSelection`\n
        `weekSelection`: _WeekID -> over this specific week | 'all' -> over all weeks"""
        if selection == "all":
            return self.__allPeriodes.cumulatedDuration() \
                + self.timeSinceClockedIn(default=timedelta(0))
        # => over a specific week
        # compute the time since clocked in during the interval
        clockedIn_periode: "Periode|None" = self.__getPeridodeSinceClockedIn()
        timeClockedIn_selection: timedelta
        if clockedIn_periode is None:
            timeClockedIn_selection = timedelta(0)
        elif clockedIn_periode.intersect(selection) is True:
            timeClockedIn_selection = clockedIn_periode.intersection(selection, "None", requirePeriode=True).duration
        else: timeClockedIn_selection = timedelta(0) # => they don't intersect 
        # compute the total time done during the interval
        selectedTimeFrameTotal: timedelta = \
            self.__allPeriodes.getSubset(selection).cumulatedDuration()
        return selectedTimeFrameTotal + timeClockedIn_selection
        
    def averageTimePer_TimeFrame(self, selectedTimeFrame:"_TimeFrame|None")->timedelta:
        """compute the average time done timeFrames based on the given `selectedTimeFrame` (None -> use selected)"""
        if selectedTimeFrame is None: 
            selectedTimeFrame = self.__selectedTimeFrame
        # => selectedTimeFrame is a _TimeFrame
        nb_TimeID: int = 0
        totalTime: timedelta = timedelta(0)
        subStorages: "dict[_TimeID, PeriodesStorage[_TimeID]]" = \
            self.__allPeriodes.splitPer_TimeFrame(selectedTimeFrame)
        # add the time of each
        for periodesStorage in subStorages.values():
            if periodesStorage.isEmpty():
                continue
            # => works this week
            totalTime += periodesStorage.cumulatedDuration()
            nb_TimeID += 1
        # add the time since clocked in
        for timeID, clockedTime in self.__getTimeClockedIn_perTimeFrame(selectedTimeFrame).items():
            totalTime += clockedTime
            if timeID not in subStorages.keys():
                # => a new timeID
                nb_TimeID += 1
        if totalTime == timedelta(0):
            # => nb_TimeID is also 0 => div by zero
            return timedelta(0)
        return totalTime / nb_TimeID
    
    def getDeltaToTargtedTime(self)->timedelta:
        """return the time remaining to do to reach the target\n
        negative values => target has been reached"""
        timeTarget: "TimeTarget" = self.getTimeTarget()
        totalTimeDuringTarget: timedelta = self.cumulatedDuration(
            self.get_TimeID(selectedTime=None, selectedTimeFrame=timeTarget.timeFrame))
        return timeTarget.targetedTime - totalTimeDuringTarget
    
    def getAccumulatedDeltaToTargtedTime(self)->timedelta:
        """return the accumulated time to the target for the intervals before the current\n
        negative values => target has been reached"""
        allPeriodesInterval: "_TimeID|None" = self.getAllPeriodesInterval()
        if allPeriodesInterval is None:
            # no periodes => nothing to accumulate
            return timedelta(0) 
        timeTarget: "TimeTarget" = self.getTimeTarget()
        targetCurrentTimeID: "_TimeID" = self.get_TimeID(
            selectedTime=None, selectedTimeFrame=timeTarget.timeFrame)
        # get all the periodes betwin before the start of the current 
        peridoesBefore: "PeriodesStorage[_TimeID]" = \
            self.__allPeriodes.getSubset(_TimeID(datetime.min, targetCurrentTimeID.startTime))
        nbTargetIntervals: int = len(peridoesBefore.splitPer_TimeFrame(timeTarget.timeFrame))
        if nbTargetIntervals == 0:
            # => no periodes in that interval
            return timedelta(0)
        return timeTarget.targetedTime * nbTargetIntervals - peridoesBefore.cumulatedDuration()
    
    def cumulatedDurationPerActivity(
            self, selectedTimeFrame:"_TimeFrame|None|Literal['all']")->"dict[Activity, timedelta]":
        """return all activities that are used during the selected interval \
            and the cummulated time per activity over the selected periode"""
        timePerActivity: "dict[Activity, timedelta]" = DefaultDict(lambda: timedelta(0))
        if selectedTimeFrame == "all":
            selectedTimeFrame = _TimeID(datetime.min, datetime.max)
        timeSelection: "_TimeID" = self.get_TimeID(None, selectedTimeFrame)
        for periode in self.__allPeriodes.getSubset(timeSelection):
            timePerActivity[periode.activity] += periode.duration
        # don't add the clockin time since it don't have an activity
        return timePerActivity
    
    ### internal operations on the datas
    
    def __internalExtends(self, 
            newPeriodes:"Sequence[Periode]", histPeriodes:"HistoryPeriodesActions", 
            histActivities:"HistoryActivities|None"=None)->"set[_UpdatedTarget]":
        """add all the new periodes but it and register the new activities (will link HistoryActivities if needed)"""
        if len(newPeriodes) == 0:
            return set() # => nothing to do
        # add the periodes
        try: self.__allPeriodes.extends(newPeriodes, histPeriodes=histPeriodes)
        except Exception as err:
            self.__trustMode = True
            histPeriodes.revert(self)
            raise err
        finally: self.__trustMode = False
        if histActivities is None:
            histActivities = HistoryActivities()
        updates: "set[_UpdatedTarget]" = {"periodes"}
        updates.update(self.__internalRegisterActivities(
            activities={periode.activity for periode in newPeriodes},
            histActivities=histActivities))
        if histActivities.isEmpty() is False:
            histPeriodes.linkHist(histActivities)
        return {"periodes"}
    
    def __internalSubstract(self, 
            periode:"Periode", histPeriodes:"HistoryPeriodesActions")->"set[_UpdatedTarget]":
        """substract the given periode"""
        try: self.__allPeriodes.substractPeriode(periode, histPeriodes=histPeriodes)
        except Exception as err:
            self.__trustMode = True
            histPeriodes.revert(self)
            raise err
        finally: self.__trustMode = False
        return {"periodes"}
    
    def __internalRegisterActivities(self, 
            activities:"set[Activity]", histActivities:"HistoryActivities")->"set[_UpdatedTarget]":
        """register the new activities of the given activities"""
        activitiesToAdd = activities.difference(self.__registeredActivities)
        if len(activitiesToAdd) != 0:
            self.__registeredActivities.update(activitiesToAdd)
            histActivities.registered(activitiesToAdd)
            return {"activity"}
        else: # => no activities to add
            return set()
    
    def __internalUnregisterActivities(self, activity:"Activity", 
                                       histActivities:"HistoryActivities")->"set[_UpdatedTarget]":
        """unregister the given activity, raise a KeyError if it can't"""
        if activity not in self.__registeredActivities:
            # => not reegistered
            raise KeyError(f"can't unregister the activity: {activity}, it isn't registered")
        if self.__allPeriodes.getActivitiesUsageCount(activity) != 0:
            # => this activity is used by periodes
            raise KeyError(f"can't unregister the activity: {activity}, there are periodes that use it")
        self.__registeredActivities.remove(activity)
        histActivities.unregistered([activity])
        return {"activity"}
    
    ### public operations on the datas
    
    
    def extends(self, newPeriodes:"Sequence[Periode]")->"set[_UpdatedTarget]":
        histPeriodes = HistoryPeriodesActions()
        updates: "set[_UpdatedTarget]" = self.__internalExtends(
            newPeriodes=newPeriodes, histPeriodes=histPeriodes)
        self.__history.addAction(histPeriodes)
        return updates
    
    def addPeriode(self, periode:"Periode") -> "set[_UpdatedTarget]":
        histPeriodes = HistoryPeriodesActions()
        updates: "set[_UpdatedTarget]" = self.__internalExtends(
            newPeriodes=[periode], histPeriodes=histPeriodes)
        self.__history.addAction(histPeriodes)
        return updates
    
    def replacePeriodes(self, oldPeriode:"Periode", 
                        newPeriodes:"Sequence[Periode]")->"set[_UpdatedTarget]":
        if len(newPeriodes) == 0:
            raise ValueError("no new periodes, use .substractPeriode to remove a periode witout adding a new one")
        histPeriodes = HistoryPeriodesActions()
        updates: "set[_UpdatedTarget]" = self.__internalSubstract(
            periode=oldPeriode, histPeriodes=histPeriodes)
        updates.update(self.__internalExtends(
            newPeriodes=newPeriodes, histPeriodes=histPeriodes))
        self.__history.addAction(histPeriodes)
        return updates
    
    def substractPeriode(self, periode:"Periode")->"set[_UpdatedTarget]":
        histPeriodes = HistoryPeriodesActions()
        updates: "set[_UpdatedTarget]" = self.__internalSubstract(
            periode=periode, histPeriodes=histPeriodes)
        self.__history.addAction(histPeriodes)
        return updates
    
    def editConfig(self, datas:"dict[_ConfigField, str]")->"set[_UpdatedTarget]":
        if len(datas) == 0:
            return set() # => nothing to edit
        histEdit = HistoryEditConfig()
        try: self.__configuration.edit(datas, histEdit=histEdit)
        except Exception as err:
            self.__trustMode = True
            histEdit.revert(self)
            raise err
        finally: self.__trustMode = False
        self.__history.addAction(histEdit)
        return (set() if histEdit.isEmpty() else {"config"})
    
    def registerActivity(self, newActivity:"Activity")->"set[_UpdatedTarget]":
        histActivities = HistoryActivities()
        updates = self.__internalRegisterActivities(
            activities={newActivity}, histActivities=histActivities)
        self.__history.addAction(histActivities)
        return (set() if histActivities.isEmpty() else updates)
    
    def unregisterActivity(self, activity:"Activity")->"set[_UpdatedTarget]":
        """unregister the given activity, raise a KeyError if it can't"""
        histActivities = HistoryActivities()
        updates = self.__internalUnregisterActivities(
            activity=activity, histActivities=histActivities)
        if histActivities.isEmpty() is False:
            self.__history.addAction(histActivities)
        return updates
    
    def mergeDatasWith(self, other:"FullDatas")->"set[_UpdatedTarget]":
        """add the periodes, registered activties of the other FullDatas into self"""
        histPeriodes = HistoryPeriodesActions()
        histActivities = HistoryActivities()
        # add the 
        updates: "set[_UpdatedTarget]" = self.__internalExtends(
            newPeriodes=list(other.__allPeriodes), histPeriodes=histPeriodes,
            histActivities=histActivities)
        updates.update(self.__internalRegisterActivities(
            activities=other.__registeredActivities, histActivities=histActivities))
        if histActivities.isEmpty() is False:
            histPeriodes.linkHist(histActivities)
        self.__history.addAction(histPeriodes)
        return updates
    
    ### dubug utils
    
    def prettyPrint(self)->None:
        prettyPrint(
            self, compact=JSON_SEMI_COMPACT_ARGS,
            specificFormats={datetime: lambda t: prettyDatetime(t, "full"), Periode: str})# type: ignore
    
    ### methodes in trusted mode
    
    def _trusted_getPeriodesStorage(self)->"PeriodesStorage[None]":
        if self.__trustMode is False: raise TrustError(self)
        return self.__allPeriodes
    
    def _trusted_getConfig(self)->"Configuration":
        if self.__trustMode is False: raise TrustError(self)
        return self.__configuration
    
    def _trusted_setClockinTime(self, value:"datetime|None")->None:
        if self.__trustMode is False: raise TrustError(self)
        self.__clockinTime = value
    
    def _trusted_getRegisteredActivities(self)->"set[Activity]":
        if self.__trustMode is False: raise TrustError(self)
        return self.__registeredActivities

    def _trusted_setSelectedTime(self, selectedTime:datetime)->None:
        if self.__trustMode is False: raise TrustError(self)
        self.__selectedTime = selectedTime

    def _trusted_setSelectedTimeFrame(self, timeFrame:"_TimeFrame")->None:
        if self.__trustMode is False: raise TrustError(self)
        self.__selectedTimeFrame = timeFrame
    
#########################################################





class PeriodesStorage(PartialyFinalClass, Generic[_T_TimeID], PrettyfyClass):
    __slots__ = ("timeframe", "__periodes", "__activitiesUsageCount", "__frozen")
    __finals__ = {"timeframe", "__periodes", "__activitiesUsageCount"}
    __prettyAttrs__ = list(__slots__)
    
    def __init__(self, timeID:"_T_TimeID", periodes:"Iterable[Periode]|None", 
                 histActions:"HistoryPeriodesActions|None") -> None:
        self.__frozen: bool = False
        self.timeframe: "_T_TimeID" = timeID
        self.__periodes: "SkipList[Periode, datetime]" = \
            SkipList([], lambda periode: periode.startTime)
        self.__activitiesUsageCount: "dict[Activity, int]" = DefaultDict(lambda: 0)
        if periodes is not None:
            self.extends(periodes, histPeriodes=histActions)
    
    def freez(self)->"Self":
        """make the storage frozen (can't be unfrozen)"""
        self.__frozen = True
        return self
    
    def addPeriode(self, periode:"Periode", histPeriodes:"HistoryPeriodesActions|None")->None:
        """add a periode to the storage\n
        it must be contained fully in self.__timeID (if setted)\n
        no needs to revert the hist if an error is raised, there will be no modifications done"""
        if self.__frozen is True: raise ValueError("can't add a periode on a frozen periodes storage")
        if (self.timeframe is not None) and (self.timeframe.fullyContain(periode) is False):
            raise ValueError(f"this storage with a setted timeID of {self.timeframe} can't fully contain the periode trying to added: {repr(periode)}")
        # => the periode can be added to this storage
        # => all periodes of the storage don't intersect each other
        intersectWith: "list[Periode]" = self.__periodes.popSubList(startKey=periode.startTime, endKey=periode.endTime)
        """all the periodes that intersect with `periode`"""
        # it can also intersect with the periode that start before `periode`
        try:
            periodeBefore: Periode = \
                self.__periodes.popBefore(periode.startTime)
            if periode.intersect(periodeBefore):
                intersectWith.append(periodeBefore)
            else: self.__periodes.append(periodeBefore)
        except KeyError: pass # no periodes before
        if len(intersectWith) == 0:
            # => new periode don't intersect with any periode of the storage
            self.__periodes.append(periode)
            # => all periodes of the storage don't intersect each other => finished
            self.__updateActivitiesCounts("added", [periode])
            if histPeriodes is not None: histPeriodes.periodesAdded([periode])
            return None        
        ### merge the periodes
        self.__updateActivitiesCounts("removed", intersectWith)
        if histPeriodes is not None: histPeriodes.periodesRemoved(intersectWith)
        # => `periode` intersect with all periodes in the sub list
        mergedPeriode: Periode = periode.mergeWithMultiple(intersectWith)
        self.__periodes.append(mergedPeriode)
        # => all periodes of the storage don't intersect each other => finished
        self.__updateActivitiesCounts("added", [mergedPeriode])
        if histPeriodes is not None: histPeriodes.periodesAdded([mergedPeriode])
        return None
        
    def extends(self, periodes:"Iterable[Periode]", histPeriodes:"HistoryPeriodesActions|None")->None:
        """add multiple periodes please refer to the docstring of .addPeriode(...) for more details\n
        if an error happend you should revert the history"""
        for periode in periodes:
            self.addPeriode(periode, histPeriodes=histPeriodes)
        
    def substractPeriode(self, periode:"Periode", histPeriodes:"HistoryPeriodesActions|None")->None:
        """substract a periode of the storage\n
        it must be contained fully in self.__timeID (if setted)\n
        no needs to revert the hist if an error is raised, there will be no modifications done"""
        if self.__frozen is True: raise ValueError("can't substract a periode from a frozen periodes storage")
        if (self.timeframe is not None) and (self.timeframe.fullyContain(periode) is False):
            raise ValueError(f"this storage with a setted timeID of {self.timeframe} can't fully contain the periode trying to substracted: {repr(periode)}")
        intersectWith: "list[Periode]" = self.__periodes.popSubList(startKey=periode.startTime, endKey=periode.endTime)
        """all the periodes that intersect with `periode`"""
        # it can also intersect with the periode that start before `periode`
        try:
            periodeBefore: Periode = \
                self.__periodes.popBefore(periode.startTime)
            if periode.intersect(periodeBefore):
                intersectWith.append(periodeBefore)
            else: self.__periodes.append(periodeBefore)
        except KeyError: pass # no periodes before
        ### substract to the periodes
        if len(intersectWith) == 0:
            # => the periode to remove don't intersect with any periode of the storage => finished
            return None
        self.__updateActivitiesCounts("removed", intersectWith)
        if histPeriodes is not None: histPeriodes.periodesRemoved(intersectWith)
        substractedPeriodes: "list[Periode]" = []
        for currentPeriode in intersectWith:
            substractedPeriodes.extend(periode.substractOf(currentPeriode))
        self.__periodes.extend(substractedPeriodes)
        self.__updateActivitiesCounts("added", substractedPeriodes)
        if histPeriodes is not None: histPeriodes.periodesAdded(substractedPeriodes)
        return None
        
        
    def getSubset(self, timeID:"_TimeID")->"PeriodesStorage[_TimeID]":
        """get a frozen subset of all the periodes inside the given `timeID`"""
        subPeriodes: "Iterable[Periode]|None" = \
            self.__periodes.getSubListView(startKey=timeID.startTime, endKey=timeID.endTime)
        # transfert 
        if subPeriodes is None: 
            subPeriodes = []
        # => subPeriodes is now an iterable only
        subStorage: "PeriodesStorage[_TimeID]" = \
            PeriodesStorage(
                timeID=timeID, histActions=None, periodes=(
                    periode.intersection(timeID, commentsMerge="self", requirePeriode=True) for periode in subPeriodes))
        # add the periode before (to add its intersection)
        try: periodeBefore: "Periode" = self.__periodes.getBefore(timeID.startTime)
        except KeyError: pass # => there is no periode before the start key
        else: # add the periode if it is inside the given timeID
            if periodeBefore.endTime >= timeID.startTime:
                subStorage.addPeriode(periodeBefore.intersection(timeID, commentsMerge="self", requirePeriode=True), histPeriodes=None)
        # freez the subset to make it safer to use
        return subStorage.freez()
    
    def getPeriodes_sortedByfield(self, field:"_PeriodeFields_sortable", ascendingOrder:bool=True)->"list[Periode]":
        return sorted(
            self.__periodes, key=lambda periode: getattr(periode, field),
            reverse=(not ascendingOrder))
    
    def getAllPeriodesInterval(self)->"_TimeID|_T_TimeID":
        """return the precise interval that holds all the periodes\n
        if it has no periodes, return its timeframe"""
        if len(self.__periodes) == 0:
            return self.timeframe
        return _TimeID(
            startTime=self.__periodes.getFirst().startTime,
            endTime=self.__periodes.getLast().endTime)
        
        
    
    def __iter__(self)->"Iterator[Periode]": 
        return iter(self.__periodes)
    def isEmpty(self)->bool: 
        return (len(self.__periodes) == 0)
    def cumulatedDuration(self)->"timedelta":
        return sum((periode.duration for periode in self.__periodes), timedelta(0))
    
    def getPeriode(self, startTime:datetime, default:"_T"=None)->"Periode|_T":
        """try to get the periode with this start time"""
        try: return self.__periodes.get(startTime)
        except KeyError: return default
    
    def splitPer_TimeFrame(self, timeFrame:"_TimeFrame")->"dict[_TimeID, PeriodesStorage[_TimeID]]": 
        result: "dict[_TimeID, PeriodesStorage[_TimeID]]" = {}
        for periode in self.__periodes:
            splits: "dict[_TimeID, Periode]" = periode.splitPer_TimeFrame(timeFrame)
            for timeID, split in splits.items():
                if timeID not in result:
                    result[timeID] = PeriodesStorage(timeID=timeID, periodes=None, histActions=None)
                result[timeID].addPeriode(split, histPeriodes=None)
        for storage in result.values():
            storage.freez()
        return result
    
    def __updateActivitiesCounts(self, actionPeridoes:"Literal['added', 'removed']", 
                                 periodes:"Sequence[Periode]")->None:
        if actionPeridoes not in ("added", "removed"):
            raise ValueError(f"invalide action: {actionPeridoes}")
        delta = (-1 if actionPeridoes == "removed" else +1)
        for periode in periodes:
            self.__activitiesUsageCount[periode.activity] += delta

    def getActivitiesUsageCount(self, activity:"Activity")->int:
        """tell how much time this activity is used (0 if the activity isn't used, never raise a KeyError)"""
        if activity not in self.__activitiesUsageCount.keys():
            return 0
        return self.__activitiesUsageCount[activity]

    def _trusted_addPeriodes(self, periodes:"Iterable[Periode]")->None:
        """add the `periodes` without any checks, update the activity counts"""
        for periode in periodes:
            self.__periodes.append(periode)
            self.__activitiesUsageCount[periode.activity] += 1
    
    def _trusted_removePeriodes(self, periodes:"Iterable[Periode]")->None:
        """remove the `periodes` without any checks, update the activity counts"""
        for periode in periodes:
            self.__periodes.remove(periode.startTime)
            self.__activitiesUsageCount[periode.activity] -= 1

#########################################################






class Periode(FinalClass, PrettyfyClass, Jsonable):
    """contiguous work periode"""
    EMPTY_COMMENT: str = ""
    __slots__ = ("startTime", "endTime", "activity", "comments", )
    
    def __init__(self, startTime:datetime, endTime:datetime, 
                 activity:"str|Activity|None", comments:"str|None") -> None:
        self.startTime: datetime = startTime
        self.endTime: datetime = endTime
        # ensure the periode isn't empty
        if self.duration < EPSILON_DURATION:
            raise ValueError(f"the duration betwin: {self.startTime} and {self.endTime} is too short, "
                             f"must be longer than: {EPSILON_DURATION} but is {self.duration}")
        # set the activity and comments
        if not isinstance(activity, Activity):
            activity = Activity(activity)
        self.activity: "Activity" = activity
        self.comments: str = (Periode.EMPTY_COMMENT if comments is None else comments)
    
    def copyContent(self, newStartTime:datetime, newEndTime:datetime)->"Periode":
        return Periode(newStartTime, newEndTime, self.activity, self.comments)
    
    def getFieldToStr(self, field:"_PeriodeField")->str:
        value = assertIsinstance((str, datetime, Activity), getattr(self, field))
        if isinstance(value, str): return value
        elif isinstance(value, datetime): return datetimeToText(value)
        elif isinstance(value, Activity): return value.__str__()
        else: raise TypeError(f"unexpected type: {type(value)} of the value: {repr(value)} of the field: {repr(field)} of the self: {repr(self)}")
        
    
    @property
    def duration(self)->timedelta:
        return self.endTime - self.startTime
    
    @property
    def midle(self)->datetime:
        return self.startTime + self.duration / 2
    
    def prettyDuration(self)->str:
        return prettyTimedelta(self.duration.total_seconds())
        
    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(startTime={datetimeToText(self.startTime)}, endTime={datetimeToText(self.endTime)}, activity={self.activity})"
    
    def __str__(self) -> str:
        activityText:str = ("" if self.activity is None else  f" doing {repr(self.activity)}")
        return f"{self.__class__.__name__}(from {prettyDatetime(self.startTime, format='full')} to {prettyDatetime(self.endTime, format='full')}, duration={self.duration}{activityText})"
    
    def __eq__(self, __other:object)->bool:
        if not isinstance(__other, Periode):
            return False
        return (self.startTime == __other.startTime) \
            and (self.endTime == __other.endTime) \
            and (self.activity == __other.activity) \
            and (self.comments == __other.comments)
    def __ne__(self, value:object) -> bool:
        return not self.__eq__(value)
    
    @classmethod
    def fromText(cls, startTime:str, endTime:str, activity:"str|None", comments:"str|None")->"Periode":
        return Periode(datetimeFromText(startTime), datetimeFromText(endTime), activity, comments)
    
    def combineableActivities(self, __other:"Periode")->bool:
        return self.activity.isCombineableWith(__other.activity)
    
    def intersect(self, __other:"Periode")->bool:
        """tell whether two periodes intersect each other"""
        if self.fullyAfter(__other): return False
        elif self.fullyBefore(__other): return False
        else: return True
    
    def fullyBefore(self, __other:"Periode")->bool:
        """return whether self is fully before __other (=> no intersection)"""
        return self.endTime < __other.startTime
    
    def fullyAfter(self, __other:"Periode")->bool:
        """return whether self is fully after __other (=> no intersection)"""
        return __other.endTime < self.startTime

    def fullyContain(self, __other:"Periode")->bool:
        """return whether __other is fully inside self (=> intersection)"""
        return (self.startTime <= __other.startTime) and (__other.endTime <= self.endTime)

    def __mergeComments(self, other:"Periode", mergeMethode:"_CommentsMerge")->"str|None":
        if mergeMethode == "None": return None
        elif mergeMethode == "self": return self.comments
        elif mergeMethode == "other": return other.comments
        else: raise ValueError(f"the merge methode: {mergeMethode} invalide")

    def mergeWith(self, __other:"Periode")->"Periode":
        """merge two periodes, keep the comment of self (they must intersect)"""
        if (self.intersect(__other) == False) or (self.combineableActivities(__other) == False):
            errorTexts: "list[str]" = []
            if self.intersect(__other) == False: errorTexts.append("intersect")
            if self.combineableActivities(__other) == False: errorTexts.append("have compatible activties")
            raise ValueError(f"self: {repr(self)} and __other: {repr(__other)}\n must {' and '.join(errorTexts)} in order to be merged")
        mergedActivity = (self.activity or __other.activity)
        return Periode(
            startTime=min(self.startTime, __other.startTime),
            endTime=max(self.endTime, __other.endTime), 
            activity=mergedActivity,
            comments=self.__mergeComments(__other, mergeMethode="self"))
    
    def mergeWithMultiple(self, __others:"Iterable[Periode]")->"Periode":
        """merge multiple periodes keep the comment of self\n
        they must all intersect with self"""
        newPeriode: Periode = self.copyContent(self.startTime, self.endTime)
        for other in __others:
            newPeriode = newPeriode.mergeWith(other)
        return newPeriode
    
    def substractOf(self, __other:"Periode")->"list[Periode]":
        """remove `self` of the `__other` periode\n
        it returns 0 periodes if it compleately erased it, 
        1 periode if it removed an end of it or removed nothing,
        2 periodes if it splited it"""
        if self.combineableActivities(__other) == False:
            raise ValueError(f"in order to substract {repr(self)} of {repr(__other)} they must have compatible activities")
        if self.intersect(__other) == False:
            return [__other]
        result:"list[Periode]" = []
        if __other.startTime < self.startTime:
            # => self erase the end of __other
            result.append(__other.copyContent(__other.startTime, self.startTime))
        if self.endTime < __other.endTime:
            # => self erase the end of __other
            result.append(__other.copyContent(self.endTime, __other.endTime))
        # result == [] 
        # <=> (__other.startTime >= self.startTime) and (self.endTime >= __other.endTime)
        # <=> (self.startTime <= __other.startTime) and (__other.endTime <= self.endTime)
        return result


    def split(self, t:datetime, spacing:"timedelta|None")->"tuple[Periode, Periode]":
        """split the two periodes and add a `spacing` between the two periodes\n
        (ths spacing is eaten for each splited periode is based on thir proportion of the remaining duration)"""
        if (t <= self.startTime) or (self.endTime <= t):
            raise ValueError(f"the split time: {datetimeToText(t)} isn't contained in the periode: {self}")
        if spacing is None: spacing = timedelta(0)
        if self.duration < spacing:
            raise ValueError(f"can't split a periode: {repr(self)} with a duration of: {self.duration} using a spacing of: {spacing}")
        # => can split it
        firstPeriodeProportion: float = (t - self.startTime) / self.duration
        """proportion of the first part relative to the total duration"""
        firstPeriode: Periode = self.copyContent(
            newStartTime=self.startTime, 
            newEndTime=(t - spacing * firstPeriodeProportion))
        secondPeriode: Periode = self.copyContent(
            newStartTime=(t + spacing * (1 - firstPeriodeProportion)),
            newEndTime=self.endTime)
        return (firstPeriode, secondPeriode)

    @overload
    def intersection(self, __other:"Periode", commentsMerge:"_CommentsMerge", 
                     requirePeriode:"Literal[True]")->"Periode": ...
    @overload
    def intersection(self, __other:"Periode", commentsMerge:"_CommentsMerge",
                     requirePeriode:"Literal[False]")->"Periode|None": ...
    def intersection(self, __other:"Periode", commentsMerge:"_CommentsMerge", requirePeriode:bool)->"Periode|None":
        """return the intersection of the self with __other (they must intersect and have comptible activites)"""
        if self.combineableActivities(__other) is False:
            raise ValueError(f"can't compute the intersection of {repr(self)} and {repr(__other)} they must have compatible activities")
        if self.intersect(__other) is False:
            if requirePeriode is False: 
                return None
            raise ValueError(f"can't compute the intersection of {repr(self)} and {repr(__other)} they must intersect and have compatible activities")
        startTime = max(self.startTime, __other.startTime)
        endTime = min(self.endTime, __other.endTime)
        if (endTime - startTime) < EPSILON_DURATION:
            # => empty periode (not possible to create)
            if requirePeriode is False:
                return None
            raise ValueError(f"can't compute the intersection of {repr(self)} and {repr(__other)} they must intersect and have compatible activities")
        return Periode(
            startTime=startTime, endTime=endTime,
            activity=self.activity.combineWith(__other.activity),
            comments=self.__mergeComments(__other, commentsMerge))
    
    def splitPer_TimeFrame(self, timeFrame:"_TimeFrame")->"dict[_TimeID, Periode]":
        splits: "dict[_TimeID, Periode]" = {}
        # ge the _timeID that contain the start of the periode
        timeID: _TimeID = _TimeID.getTimeID(self.startTime, timeFrame)
        while self.intersect(timeID):
            intersection: "Periode|None" = self.intersection(timeID, commentsMerge="self", requirePeriode=False)
            if intersection is not None:
                splits[timeID] = intersection
            timeID = timeID.next()
        return splits

    def toJson(self)->"AsJson_Periode":
        return AsJson_Periode(
            cls=self.__class__.__name__,
            startTime=datetimeToJson(self.startTime),
            endTime=datetimeToJson(self.endTime),
            activity=self.activity.toJson(),
            comments=self.comments,
        )

    @classmethod
    def fromJson(cls, datas:"AsJson_Periode")->"Self":
        assert datas["cls"] == cls.__name__
        periode = Periode.__new__(cls)
        Periode.__init__(
            self=periode, 
            startTime=datetimeFromJson(datas["startTime"]),
            endTime=datetimeFromJson(datas["endTime"]),
            activity=Activity.fromJson(datas["activity"]),
            comments=datas["comments"],
        )
        return periode

    def __hash__(self)->int:
        return hash((self.startTime, self.endTime, self.activity, self.comments))
    
    def getHashDetails(self)->"tuple[int, ...]":
        return (hash(self), hash(self.startTime), hash(self.endTime), hash(self.activity), hash(self.comments))

#########################################################






class _TimeID(Periode, addPrettyAttrs_fromBases=False):
    __prettyAttrs__ = (["startTime", "endTime"], False)
    
    def __init__(self, startTime:datetime, endTime:datetime) -> None:
        super().__init__(startTime=startTime, endTime=endTime, activity=None, comments=None)
        
    @property
    def lastTime(self)->datetime:
        """the last moment before self.endTime"""
        return self.endTime - EPSILON_DURATION

    def __contains__(self, t:datetime)->bool:
        return (self.startTime <= t) and (t < self.endTime)

    def next(self)->"_TimeID":
        return _TimeID(startTime=self.endTime, endTime=self.endTime+self.duration)
    def prev(self)->"_TimeID":
        return _TimeID(startTime=self.startTime-self.duration, endTime=self.startTime)
    
    def prettyText(self)->str:
        return f"from {prettyDatetime(self.startTime, 'auto')} to {prettyDatetime(self.lastTime, 'auto')}"
    def prettyTimeFrameText(self)->str:
        return f"from {prettyDatetime(self.startTime, 'auto')} of {prettyTimedelta(self.duration, useDays=True)}"
    def __str__(self) -> str:
        return f"{self.__class__.__name__}(from {prettyDatetime(self.startTime, 'auto')} to {prettyDatetime(self.endTime, 'auto')}, duration of {prettyTimedelta(self.duration)})"
    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(startTime={datetimeToText(self.startTime)}, endTime={datetimeToText(self.endTime)}, duration:{self.duration})"
    
    @staticmethod
    def getTimeID(t:datetime, timeFrame:"_TimeFrame")->"_TimeID":
        """return the _TimeID that contain the moment `t` based on the given `timeFrame`"""
        if timeFrame == "day": return _DayID.fromDatetime(t)
        elif timeFrame == "week": return _WeekID.fromDatetime(t)
        elif timeFrame == "month": return _MonthID.fromDatetime(t)
        elif timeFrame == "year": return _YearID.fromDatetime(t)
        elif isinstance(timeFrame, _TimeID): return timeFrame.shiftTo(t)
        else: raise ValueError(f"invalide timeFrame: {timeFrame}")
    
    @classmethod
    def fromDuration(cls, startTime:datetime, duration:timedelta)->"_TimeID":
        return _TimeID(startTime=startTime, endTime=startTime+duration)
    
    def shiftTo(self, t:datetime)->"_TimeID":
        """return the _TimeID that contain `t` by shifting `self`, in O(1) beacause it don't use .next/prev but the duration"""
        t2 = self.startTime + ((t - self.startTime) // self.duration) * self.duration
        return _TimeID(startTime=t2, endTime=t2+self.duration)

    def __hash__(self) -> int:
        return hash((self.startTime, self.endTime))

    def asTimeID(self)->"_TimeID":
        return _TimeID(self.startTime, self.endTime)

    @classmethod
    @override
    def fromText(cls, startTime:str, endTime:str)->"_TimeID":
        return _TimeID(datetimeFromText(startTime), datetimeFromText(endTime))

    @classmethod
    def getExemple(cls)->"_TimeID":
        return _WeekID.fromDatetime(datetime.now()).asTimeID()

class _YearID(_TimeID):
    
    @classmethod
    def fromDatetime(cls, t:datetime) -> "_YearID":
        return _YearID(startTime=datetime(year=t.year, month=1, day=1),
                       endTime=datetime(year=t.year+1, month=1, day=1))
        
    def next(self)->"_YearID":
        return _YearID(startTime=self.endTime, endTime=self.endTime.replace(year=self.endTime.year+1))
    def prev(self)->"_YearID":
        return _YearID(startTime=self.startTime.replace(year=self.startTime.year-1), endTime=self.startTime)
    
    @override
    def prettyText(self)->str: return f"from {prettyDatetime(self.startTime, 'date')} to {prettyDatetime(self.lastTime, 'date')}"
    
    
class _MonthID(_TimeID):
    
    @classmethod
    def fromDatetime(cls, t:datetime) -> "_MonthID":
        return _MonthID(startTime=datetime(year=t.year, month=t.month, day=1), 
                        endTime=datetime(*cls.__nextMonth(t), day=1))
    
    @classmethod
    def __nextMonth(cls, t:datetime)->"tuple[int, int]":
        if t.month == 12: return (t.year+1, 1)
        else: return (t.year, t.month+1)
    @classmethod
    def __prevMonth(cls, t:datetime)->"tuple[int, int]":
        if t.month == 1: return (t.year-1, 12)
        else: return (t.year, t.month-1)
    
    def next(self)->"_MonthID":
        nextEndTime = datetime(*self.__nextMonth(self.endTime), day=1)
        return _MonthID(startTime=self.endTime, endTime=nextEndTime)
    def prev(self)->"_MonthID":
        prevStartTime = datetime(*self.__prevMonth(self.startTime), day=1)
        return _MonthID(startTime=prevStartTime, endTime=self.startTime)
    
    @override
    def prettyText(self)->str: return f"from {prettyDatetime(self.startTime, 'date')} to {prettyDatetime(self.lastTime, 'date')}"
    
class _WeekID(_TimeID):
    
    @classmethod
    def fromDatetime(cls, t:datetime) -> "_WeekID":
        week = t.isocalendar()[1]
        startTime: datetime =  datetime.strptime(f"{t.year}-{week}-1", "%Y-%W-%w")
        return _WeekID(startTime=startTime, endTime=startTime+timedelta(days=7))
    
    @override
    def prettyText(self)->str: return f"from {prettyDatetime(self.startTime, 'date')} to {prettyDatetime(self.lastTime, 'date')}"

    
class _DayID(_TimeID):
    
    @classmethod
    def fromDatetime(cls, t:datetime) -> "_DayID":
        startTime: datetime = datetime(year=t.year, month=t.month, day=t.day)
        return _DayID(startTime=startTime, endTime=startTime+timedelta(days=1))

    @override
    def prettyText(self)->str: return f"the {prettyDatetime(self.startTime, 'date')} from {prettyDatetime(self.endTime, 'time')} to {prettyDatetime(self.lastTime, 'time')}"







#########################################################








class Activity(FinalClass):
    EMPTY_ACTIVITIES: "set[str]" = {"", "/", "None"}
    __slots__ = ("__value", )
    
    def __init__(self, value:"str|None")->None:
        self.__value: "None|str"
        if value is None: self.__value = None
        else: # => might be different than None
            value = value.strip()
            self.__value = (None if value in Activity.EMPTY_ACTIVITIES else value)
    
    def combineWith(self, __other:"Activity")->"Activity":
        """combine two activities, they must be compatible"""
        if self.isCombineableWith(__other) is False:
            raise ValueError(f"{self} is incompatible with {__other}")
        return Activity(value=(self.__value or __other.__value))
    
    def isEmpty(self)->bool:
        return self.__value is None
    
    def isCombineableWith(self, __other:"Activity")->bool:
        if self.isEmpty() or __other.isEmpty():
            return True
        return self.__value == __other.__value
    
    def __eq__(self, value: "Activity|str|None|object") -> bool:
        if isinstance(value, (str, type(None))):
            value = Activity(value)
        elif not isinstance(value, Activity):
            raise TypeError(f"invalide type to compare an Activity: {self} with the value: {value}")
        # => value is an Activity
        return self.__value == value.__value
    def __hash__(self) -> int: return hash(self.__value)
    def __str__(self) -> str: return (self.__value or "/")
    def __repr__(self) -> str: return repr(str(self))

    def __lt__(self, __other: "Activity")->bool:
        if not isinstance(__other, Activity):
            return NotImplemented
        return str(self) < str(__other)

    @classmethod
    def fromJson(cls, datas:"AsJson_Activity")->"Self":
        assert datas["cls"] == cls.__name__
        activity = Activity.__new__(cls)
        Activity.__init__(activity, value=datas["activity"])
        return activity

    def toJson(self)->"AsJson_Activity":
        return AsJson_Activity(cls=self.__class__.__name__, activity=self.__value)


#########################################################






class PrettyTimedelta(timedelta):
    @classmethod
    def fromTimedelta(cls, t:timedelta)->"PrettyTimedelta":
        return PrettyTimedelta(seconds=t.total_seconds())
    @classmethod
    def fromText(cls, text:str)->"PrettyTimedelta":
        return cls.fromTimedelta(timedeltaFromText(text))
    def __str__(self) -> str:
        return prettyTimedelta(self)
    
    @classmethod
    def fromJson(cls, datas:"AsJson_PrettyTimedelta")->"Self":
        assert datas["cls"] == cls.__name__
        return PrettyTimedelta.__new__(
            cls, seconds=assertIsinstance(float, datas["seconds"]))

    def toJson(self)->"AsJson_PrettyTimedelta":
        return AsJson_PrettyTimedelta(
            cls=self.__class__.__name__,
            seconds=self.total_seconds())




#########################################################



class TimeTarget(PrettyfyClass, Jsonable):
    __slots__ = ("targetedTime", "timeFrame", )
    def __init__(self, targetedTime:timedelta, timeFrame:"_TimeFrame")->None:
        self.targetedTime: PrettyTimedelta = \
            PrettyTimedelta.fromTimedelta(targetedTime)
        self.timeFrame: "_TimeFrame" = timeFrame
    
    def toJson(self) -> "AsJson_TimeTarget":
        return AsJson_TimeTarget(
            cls=self.__class__.__name__,
            targetedTime=self.targetedTime.toJson(),
            timeFrame=timeFrameToJson(self.timeFrame))
    
    @classmethod
    def fromJson(cls, datas:"AsJson_TimeTarget") -> Self:
        assert datas["cls"] == cls.__name__
        timeTarget: Self = TimeTarget.__new__(cls)
        TimeTarget.__init__(
            self=timeTarget, 
            targetedTime=PrettyTimedelta.fromJson(datas["targetedTime"]),
            timeFrame=timeFrameFromJson(datas["timeFrame"]))
        return timeTarget
        


#########################################################




class Configuration(PrettyfyClass):
    __slots__ = ("name", "description", "targetedTime", "targetedTimeFrame", )
    assert set(__slots__) == set(get_args(_ConfigField))
    
    def __init__(self, name:str, description:str, targetPerPeriode:"TimeTarget") -> None:
        self.name: str = name
        self.description: str = description
        self.targetedTime: "PrettyTimedelta" = targetPerPeriode.targetedTime
        self.targetedTimeFrame: "_TimeFrame" = targetPerPeriode.timeFrame

    @classmethod
    def createEmpty(cls)->"Configuration":
        return Configuration(
            name="no name", description="no description provided", 
            targetPerPeriode=TimeTarget(timedelta(0), "week"))

    @classmethod
    def fromText(cls, datas:"dict[_ConfigField, str]")->"Self":
        assert set(datas.keys()) == set(get_args(_ConfigField))
        config = Configuration.__new__(cls)
        for field, text in datas.items():
            setattr(config, field, config.__convertField(field, text))
        return config

    def getTimeTarget(self)->"TimeTarget":
        return TimeTarget(targetedTime=self.targetedTime, timeFrame=self.targetedTimeFrame)
    
    def __convertField(self, field:"_ConfigField", data:"str")->"str|PrettyTimedelta|_TimeFrame|bool":
        if isinstance(data, str) is False:
            raise ValueError(f"invalide value: {repr(data)} for the field: {field}")
        if field in ("description", "name"):
            return assertIsinstance(str, data)
        elif field == "targetedTime":
            return PrettyTimedelta.fromText(data)
        elif field == "targetedTimeFrame":
            return timeFrameFromText(data)
        elif field == "accumulateDeltaToTarget":
            return bool(data)
        else: raise AttributeError(f"invalide field: {field}")

    def getFieldValueAsText(self, field:"_ConfigField")->str:
        """convert to text the value at the given `field` of the config\n
        does the opposit of self.__convertField(...)"""
        if field in ("description", "name"):
            return assertIsinstance(str, getattr(self, field))
        elif field == "targetedTime":
            return self.targetedTime.__str__()
        elif field == "targetedTimeFrame":
            return timeFrameToText(self.targetedTimeFrame)
        else: raise AttributeError(f"invalide field: {field}")
        
    def edit(self, datas:"dict[_ConfigField, str]", histEdit:"HistoryEditConfig|None")->None:
        for field, data in datas.items():
            assert field in self.__slots__
            oldData = self.getFieldValueAsText(field)
            setattr(self, field, self.__convertField(field, data))
            if histEdit is not None:
                histEdit.editField(field, oldData, data)
    
    def copy(self)->"Configuration":
        return Configuration(
            name=self.name, description=self.description,
            targetPerPeriode=self.getTimeTarget())
            
    def toJson(self)->"AsJson_Configuration":
        return AsJson_Configuration(
            cls=self.__class__.__name__,
            name=self.name, description=self.description,
            targetedTimePerPeriode=self.getTimeTarget().toJson())

    @classmethod
    def fromJson(cls, datas:"AsJson_Configuration")->"Self":
        assert datas["cls"] == cls.__name__
        config = Configuration.__new__(cls)
        Configuration.__init__(
            self=config,
            name=datas["name"],
            description=datas["description"],
            targetPerPeriode=TimeTarget.fromJson(datas["targetedTimePerPeriode"]))
        return config
    

#########################################################
    
class History(_HistoryBackend["HistoryAction"]):
        
    def revertOne(self, datas:FullDatas)->"set[_UpdatedTarget]":
        """try to revert the last action on the `datas`, raise a NoHistoryError if there is no history available"""
        return super().undoOne().revert(datas)
        
    def redoOne(self, datas:FullDatas)->"set[_UpdatedTarget]":
        """try to redo last action on the `datas`, raise a NoHistoryError if there is no history available"""
        return super().redoOne().applie(datas)

    def addAction(self, action:"HistoryAction")->None:
        self.addCheckpoint(value=action)
    
#########################################################


class HistoryAction(FinalClass, ABC, PrettyfyClass):
    """abstract base class to describe actions on the datas (to have a simple history)"""
    __slots__ = ("__linkedHists", )
    def __init__(self) -> None:
        self.__linkedHists: "set[HistoryAction]" = set()
        """the hists that are linked to a single action"""
    
    def linkHist(self, otherHistory:"HistoryAction")->None:
        """link an other history to this one, you can link the same history multiple time\n
        linked history will be reverted at the same time as self so they must do independent actions"""
        self.__linkedHists.add(otherHistory)
    
    @abstractmethod
    def revert(self, datas:FullDatas)->"set[_UpdatedTarget]":
        """revert the action done to the datas (used to undo an action)"""
        updates: "set[_UpdatedTarget]" = set()
        for hist in self.__linkedHists:
            updates.update(hist.revert(datas))
        return updates
        
    @abstractmethod
    def applie(self, datas:FullDatas)->"set[_UpdatedTarget]":
        """applie the action to the datas (used to redo a reverted action)"""
        updates: "set[_UpdatedTarget]" = set()
        for hist in self.__linkedHists:
            updates.update(hist.applie(datas))
        return updates

    @abstractmethod
    def isEmpty(self)->bool:
        """return whether the action and the actions linked are empty"""
        return all(hist.isEmpty() for hist in self.__linkedHists)

class HistoryPeriodesActions(HistoryAction):
    __slots__ = ("__subActions", )
    def __init__(self) -> None:
        super().__init__()
        self.__subActions: "list[tuple[_SubActionType, list[Periode]]]" = []
        """from first actions done to the last done (they must not be empty)"""
    
    def periodesAdded(self, addedPeriodes:"Iterable[Periode]")->None:
        addedPeriodes = list(addedPeriodes)
        if len(addedPeriodes) == 0:
            return None # no periodes were added
        # => sub action wil not be empty
        self.__subActions.append(("added", addedPeriodes))
    def periodesRemoved(self, removedPeriodes:"Iterable[Periode]")->None:
        removedPeriodes = list(removedPeriodes)
        if len(removedPeriodes) == 0:
            return None # no periodes were removed
        # => sub action wil not be empty
        self.__subActions.append(("removed", removedPeriodes))
    
    @override
    def revert(self, datas:FullDatas)->"set[_UpdatedTarget]":
        updates: "set[_UpdatedTarget]" = super().revert(datas)
        periodesStorage: "PeriodesStorage[None]" = \
            datas._trusted_getPeriodesStorage()
        del datas
        for (actionType, periodes) in reversed(self.__subActions):
            if actionType == "added":
                periodesStorage._trusted_removePeriodes(periodes)
            elif actionType == "removed":
                periodesStorage._trusted_addPeriodes(periodes)
            else: raise ValueError(f"unknown actionType: {actionType}")
            updates.add("periodes")
        return updates

    def applie(self, datas:FullDatas)->"set[_UpdatedTarget]":
        updates: "set[_UpdatedTarget]" = super().applie(datas)
        periodesStorage: "PeriodesStorage[None]" = \
            datas._trusted_getPeriodesStorage()
        del datas
        for (actionType, periodes) in self.__subActions:
            if actionType == "added":
                periodesStorage._trusted_addPeriodes(periodes)
            elif actionType == "removed":
                periodesStorage._trusted_removePeriodes(periodes)
            else: raise ValueError(f"unknown actionType: {actionType}")
            updates.add("periodes")
        return updates
    
    @override
    def isEmpty(self)->bool:
        return isEmptySubActions(self.__subActions) and super().isEmpty()
    
class HistoryClockingAction(HistoryAction):
    __slots__ = ("__clockinValue", "__actionType", )
    def __init__(self, clockinValue:"datetime", 
                 action:"Literal['clockedin', 'unclockedin']") -> None:
        super().__init__()
        self.__clockinValue: datetime = clockinValue
        self.__actionType: "Literal['clockedin', 'unclockedin']" = action
    
    def revert(self, datas:FullDatas)->"set[_UpdatedTarget]":
        updates: "set[_UpdatedTarget]" = super().revert(datas)
        if self.__actionType == "clockedin":
            datas._trusted_setClockinTime(None)
        elif self.__actionType == "unclockedin":
            datas._trusted_setClockinTime(self.__clockinValue)
        else: raise ValueError(f"unknown actionType: {self.__actionType}")
        updates.add("clockin")
        return updates
    
    def applie(self, datas:FullDatas)->"set[_UpdatedTarget]":
        updates: "set[_UpdatedTarget]" = super().applie(datas)
        if self.__actionType == "clockedin":
            datas._trusted_setClockinTime(self.__clockinValue)
        elif self.__actionType == "unclockedin":
            datas._trusted_setClockinTime(None)
        else: raise ValueError(f"unknown actionType: {self.__actionType}")
        updates.add("clockin")
        return updates
    
    @override
    def isEmpty(self)->bool:
        # it always toogle a state, can't be empty
        return False 

class HistoryEditConfig(HistoryAction):
    __slots__ = ("__oldDatas", "__newDatas", )
    def __init__(self) -> None:
        super().__init__()
        self.__oldDatas: "dict[_ConfigField, str]" = {}
        self.__newDatas: "dict[_ConfigField, str]" = {}
        
    def editField(self, field:"_ConfigField", oldData:str, newData:str)->None:
        """note the edit of the field if `oldData` != `newData`"""
        if field in self.__oldDatas.keys():
            raise RuntimeError(f"tying to re edit the field: {field} it should be in an other action")
        if oldData == newData: 
            return None # => no modification
        self.__oldDatas[field] = oldData
        self.__newDatas[field] = newData
    
    def revert(self, datas:FullDatas)->"set[_UpdatedTarget]": 
        updates: "set[_UpdatedTarget]" = super().revert(datas)
        datas._trusted_getConfig().edit(self.__oldDatas, histEdit=None)
        updates.add("config")
        return updates
    
    def applie(self, datas:FullDatas)->"set[_UpdatedTarget]": 
        updates: "set[_UpdatedTarget]" = super().applie(datas)
        datas._trusted_getConfig().edit(self.__newDatas, histEdit=None)
        updates.add("config")
        return updates

    @override
    def isEmpty(self)->bool:
        if len(self.__oldDatas) != 0:
            # => self not empty
            return False
        # => self is empty
        return super().isEmpty()

class HistoryActivities(HistoryAction):
    __slots__ = ("__subActions", )
    def __init__(self) -> None:
        super().__init__()
        self.__subActions: "list[tuple[_SubActionType, list[Activity]]]" = []
        """from first actions done to the last done (they must not be empty)"""
    
    def registered(self, registeredActivities:"Iterable[Activity]")->None:
        registeredActivities = list(registeredActivities)
        if len(registeredActivities) == 0:
            return None # no activity to were registered
        # => sub action wil not be empty
        self.__subActions.append(("added", registeredActivities))
    def unregistered(self, unregisteredActivities:"Iterable[Activity]")->None:
        unregisteredActivities = list(unregisteredActivities)
        if len(unregisteredActivities) == 0:
            return None # no activity were unregistered
        # => sub action wil not be empty
        self.__subActions.append(("removed", unregisteredActivities))
    
    @override
    def revert(self, datas:FullDatas)->"set[_UpdatedTarget]":
        updates: "set[_UpdatedTarget]" = super().revert(datas)
        rawRegisteredActivities: "set[Activity]" = \
            datas._trusted_getRegisteredActivities()
        del datas
        for (actionType, activties) in reversed(self.__subActions):
            if actionType == "added":
                rawRegisteredActivities.difference_update(activties)
            elif actionType == "removed":
                rawRegisteredActivities.update(activties)
            else: raise ValueError(f"unknown actionType: {actionType}")
            updates.add("activity")
        return updates
    
    @override
    def applie(self, datas:FullDatas)->"set[_UpdatedTarget]":
        updates: "set[_UpdatedTarget]" = super().applie(datas)
        rawRegisteredActivities: "set[Activity]" = \
            datas._trusted_getRegisteredActivities()
        del datas
        for (actionType, activties) in reversed(self.__subActions):
            if actionType == "added":
                rawRegisteredActivities.update(activties)
            elif actionType == "removed":
                rawRegisteredActivities.difference_update(activties)
            else: raise ValueError(f"unknown actionType: {actionType}")
            updates.add("activity")
        return updates

    @override
    def isEmpty(self)->bool:
        return isEmptySubActions(self.__subActions) and super().isEmpty()


class HistorySelectedTimeFrame(HistoryAction):
    __slots__ = ("__oldSelection", "__newSelection", )
    def __init__(self, oldSelection:"_TimeFrame", newSelection:"_TimeFrame") -> None:
        super().__init__()
        self.__oldSelection: "_TimeFrame" = oldSelection
        self.__newSelection: "_TimeFrame" = newSelection
    
    def revert(self, datas:FullDatas)->"set[_UpdatedTarget]": 
        updates: "set[_UpdatedTarget]" = super().revert(datas)
        datas._trusted_setSelectedTimeFrame(self.__oldSelection)
        updates.add("selectedTimeFrame")
        return updates
    
    def applie(self, datas:FullDatas)->"set[_UpdatedTarget]": 
        updates: "set[_UpdatedTarget]" = super().applie(datas)
        datas._trusted_setSelectedTimeFrame(self.__newSelection)
        updates.add("selectedTimeFrame")
        return updates

    @override
    def isEmpty(self)->bool:
        if self.__oldSelection != self.__newSelection:
            # => self not empty
            return False
        # => self is empty
        return super().isEmpty()



class HistorySelectedTime(HistoryAction):
    __slots__ = ("__oldTime", "__newTime", )
    def __init__(self, oldTime:"datetime", newTime:"datetime") -> None:
        super().__init__()
        self.__oldTime: "datetime" = oldTime
        self.__newTime: "datetime" = newTime
    
    def revert(self, datas:FullDatas)->"set[_UpdatedTarget]": 
        updates: "set[_UpdatedTarget]" = super().revert(datas)
        datas._trusted_setSelectedTime(self.__oldTime)
        updates.add("selectedTime")
        return updates
    
    def applie(self, datas:FullDatas)->"set[_UpdatedTarget]": 
        updates: "set[_UpdatedTarget]" = super().applie(datas)
        datas._trusted_setSelectedTime(self.__newTime)
        updates.add("selectedTime")
        return updates

    @override
    def isEmpty(self)->bool:
        if self.__oldTime != self.__newTime:
            # => self not empty
            return False
        # => self is empty
        return super().isEmpty()

#########################################################

