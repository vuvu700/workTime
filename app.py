from io import BufferedReader, TextIOWrapper
from datetime import datetime, timedelta
from pathlib import Path
import functools
import tkinter.dialog
import tkinter.font
from abc import ABC, abstractmethod
import ctypes
import os
import argparse

# import pdfschedule

import tkinter
import tkinter.ttk
import tkinter.filedialog
import tkinter.messagebox
from tkinter.font import Font

from model import (
    _ConfigField, _PeriodeField, _UpdatedTarget, _TimeFrame, _TimeFrame_literals, 
    FullDatas, Periode, TimeTarget, _TimeID, PeriodesStorage, Activity, NoHistoryError,
    prettyTimedelta, datetimeToText, datetimeFromText, prettyDatetime, timedeltaFromText,
    prettyTimeFrame, timeFrameToText, timeFrameFromText,
)
from utils import (
    _PeriodeColumn, _PeriodeColumn_TO_PeriodeField,
    _UpdatedALLTarget, _SaveResponse, _ActivityColumn,
)
from generateScheduleView import drawSchedule
from projectPaths import (
    DATAS_DIRECTORY, ICON_PATH, LOGGS_FILE_PATH, SCHEDULES_DIRECTORY,
)

from holo.protocols import SupportsContext, Protocol, SupportsRichComparison
from holo.__typing import (
    get_args, assertIsinstance, override,
    Callable, TracebackType, Literal, Iterable, TypedDict, )
from holo.logger import Logger
from holo.__typing import Generic, TypeVar, LiteralString


_T_TableColumn = TypeVar("_T_TableColumn", bound=LiteralString)
_T_TableElement = TypeVar("_T_TableElement", Activity, Periode)

# TODO: (IDEA, not to implement right now !!!)
# change the way edit periode dialogs are manage:
# only one at the time is allowed, place it on the midle of the app
# when oppening a new one, ask a YES/NO: 
#   "a periode edit dialog is alredy oppened dou you whant to close it ?"

# TODO: implement a stack (or a focus tree) of top levels that where focused
#   when the current top level is closed, focus the previous one
#   (find the ordering rule to make it feel confortable to use)
# when deiconify -> use that order

# TODO: try tu use a date selector aside the text to fine edit the periodes

# TODO: add the menu to generate a schedule view of the periodes of the week
# option 1: generate for the current selected interval (one column per day, even partial)
# option 2: compute the average across the days of the timeFrame (with a heatmap)


#~# only update the stats when they are visible + use a scrollbar for the stats
#~# -> property visible on statLine \w getter/setter, not visible -> don't update the stat
# pour les states: un choix entre (1)"current selected periode" | (2)"global"
# (1) cumulated time betwin <periode selected>: ... 
# (2) total Time: ... 
# (2) average time per <selected time frame>: ...
# (1, 2) targeted time to do: 
#      <targetedTime> each <targetedPeriode>
# (1, 2) delta to target: <delta> (remaining to do | over the target)
# TODO: implement thoes states --->>>
# (1 [if <subTimeFrame> != <timeFrame>]) average per sub periode:
#   - <subPeriode1>: ...
#   - <subPeriode2>: ... etc
# (1 cummulated, 2 total) time per Activity: 
#   - <activity1>: ... 
#   - <activity2>: ... etc

DATAS_FILE_TYPES: "list[tuple[str, str]]" = [("JSON", ".json"), ]
"""the file types that are accepted for the datas: [(name, .extention), ...]"""
SCHEDULE_FILE_TYPES: "list[tuple[str, str]]" = [
    ("SVG", ".svg"), ("HTML", ".html")]


# can't be moved to utils :(
def getSelectedTimeInterval(startIntervalText:str, endIntervalText:str, datas:"FullDatas")->"_TimeID":
    allPeriodesInterval = datas.getAllPeriodesInterval()
    if allPeriodesInterval is None:
        allPeriodesInterval = datas.get_TimeID(None, None)
    return _TimeID(
        startTime=(allPeriodesInterval.startTime if startIntervalText == "all" 
                    else datetimeFromText(startIntervalText)),
        endTime=(allPeriodesInterval.endTime if endIntervalText == "all"
                    else datetimeFromText(endIntervalText)))

class App():
    datas: FullDatas
    tkinterRoot: "MainFrame"
    
    def __init__(self, args:"Args") -> None:
        if args["openDatasPath"] is None:
            self.datas = FullDatas.create_empty()
        else: # => path to load is given
            with open(args["openDatasPath"], mode="rb") as file:
                self.datas = FullDatas.fromFile(file)
            del file
        self.tkinterRoot = MainFrame(self)
        
        self.tkinterRoot.protocol("WM_DELETE_WINDOW", self.exit)
        self.tkinterRoot.title("work periodes app")
        self.tkinterRoot.iconbitmap(ICON_PATH)
        # bind the inconify / uninconify
        self.tkinterRoot.bind("<Map>", self.deiconifyAll)
        self.tkinterRoot.bind("<Unmap>", self.iconifyAll)
    
    def exit(self)->None:
        saveResponse = self.askToSave()
        if saveResponse == "canceled": return None
        elif saveResponse == "done": pass # => can exit
        else: raise ValueError(f"invalide save response: {saveResponse}")
        self.tkinterRoot.destroy()
        del self.tkinterRoot, self.datas
    
    def askFilenameToSaveGeneric(
            self, master:"tkinter.Misc", title:str,
            directory:"Path|None", fileExtentions:"list[tuple[str, str]]")->"Path|None":
        fileName = tkinter.filedialog.asksaveasfilename(
            initialdir=directory, parent=master, 
            defaultextension=(None if len(fileExtentions) == 0 
                              else fileExtentions[0][1]),
            filetypes=fileExtentions, title=title)
        if fileName == "":
            return None
        return Path(fileName)
    
    def askFilenameToSaveDatas(self, master:"tkinter.Misc")->"Path|None":
        return self.askFilenameToSaveGeneric(
            master=master, title="select file to save the datas",
            directory=DATAS_DIRECTORY, fileExtentions=DATAS_FILE_TYPES)
    
    def askToSave(self)->"_SaveResponse":
        """ask the app tho save the datas if needed"""
        if self.datas.isSaved() is True:
            return "done"
        # ask to save it
        response = tkinter.messagebox.askquestion(
            title="unsaved datas",
            message="the datas has been modified since last save\n" 
                        + "do you whant to save the modifications before closing the app ?",
            type=tkinter.messagebox.YESNOCANCEL)
        if response == tkinter.messagebox.YES:
            # save the datas
            hasSaved = self.tkinterRoot.menus.saveToFile()
            if hasSaved is False:
                return "canceled" # canceled saving => don't close
            return "done"
        elif response == tkinter.messagebox.NO:
            return "done" # do nothing and quit
        elif response == tkinter.messagebox.CANCEL:
            return "canceled" # abort closing the app
        else: raise ValueError(f"invalide response: {response}")
    
    def safeSaveToFile(self, datas:"None|FullDatas", filePath:"Path")->"Literal[True]":
        """to save the datas in a safe way in the file at the given path\n
        None => use the datas of the app"""
        # backup tyhe content to avoid loosing the datas
        if datas is None: 
            datas = self.datas
        if filePath.exists():
            with open(filePath, mode="rb") as file:
                backupRawContent: bytes = file.read()
        else: backupRawContent = bytes()
        try:
            with open(filePath, mode="w") as file:
                datas.saveToFile(file)
        except Exception as err: # rewrite the backup content
            with open(filePath, mode="wb") as file:
                file.write(backupRawContent)
            tkinter.messagebox.showinfo(
                title="backup restored", message="the datas in the file are restored as they were before saving")
            raise err
        else: # => the save was successfull
            tkinter.messagebox.showinfo(title="save info", message="saved the datas")
            return True
    
    
    def iconifyAll(self, event:"tkinter.Event[tkinter.Misc]")->None:
        if event.widget.winfo_name() != self.tkinterRoot.winfo_name():
            return None # => not the root
        # iconify all the dialogs
        self.tkinterRoot.iconifyAll()
    
    def deiconifyAll(self, event:"tkinter.Event[tkinter.Misc]")->None:
        #print("app: (2) deiconifyAll", end=" -- ")
        if event.widget.winfo_name() != self.tkinterRoot.winfo_name():
            return None # => not the root
        # iconify all the dialogs
        self.tkinterRoot.deiconifyAll()
    
    def useDatas(self, datas:"FullDatas", saveResponse:"_SaveResponse")->None:
        # assert that it is allowed to save
        if saveResponse != "done":
            raise ValueError(f"not allowed to save, response was: {saveResponse}")
        # replace old datas with the new datas
        self.tkinterRoot.destroyAllRegisteredDialogs()
        self.datas = datas
        self.updatedDatas(_UpdatedALLTarget)
    
    def newEmptyDatas(self)->None:
        # ask to save the current datas
        saveResponse = self.askToSave()
        if saveResponse == "canceled":
            return None
        # change the datas
        self.useDatas(FullDatas.create_empty(), saveResponse=saveResponse)
        
    def run(self)->None:
        self.tkinterRoot.mainloop()
    
    def updatedDatas(self, targets:"set[_UpdatedTarget]")->None:
        """to call when the datas have been updated"""
        if len(targets) == 0:
            return None # => nothing to update
        self.tkinterRoot.updateDatas(targets)
    
    def revert(self, currentWindow:"tkinter.Toplevel|None"=None)->None:
        """revert the previous action done on the datas then focus the `currentWindow` (None -> main app)"""
        try: self.updatedDatas(self.datas.revert())
        except NoHistoryError:
            tkinter.messagebox.showwarning("impossible to revert", "there is not more history, it can't revert")
        (currentWindow or self.tkinterRoot).focus()
            
    def redo(self, currentWindow:"tkinter.Toplevel|None"=None)->None:
        """revert the previous action done on the datas then focus the `currentWindow` (None -> main app)"""
        try: self.updatedDatas(self.datas.redo())
        except NoHistoryError:
            tkinter.messagebox.showwarning("impossible to redo", "there is not more history, it can't redo")
        (currentWindow or self.tkinterRoot).focus()



class MainFrame(tkinter.Tk):
    application: App
    menus: "MenusWidget"
    statsFrame: "StatsFrame"
    periodesFrame: "PerodesFrame"
    buttonsFrame: "ActionsFrame"
    fonts: "FontsManger"
    
    def __init__(self, app:App) -> None:
        super().__init__()
        self.application:App = app
        self.__periodeDialogs: "dict[Periode, PeriodeDialog]" = {}
        self.fonts: FontsManger = FontsManger(self, normal=None)
        
        
        self.configure(background="white")
        self.resizable(width=False, height=False)
        self.geometry("1024x720")
        self.grid_columnconfigure(0, weight=1) # stats 
        self.grid_columnconfigure(1, weight=4) # periodes
        self.grid_rowconfigure(0, weight=4) # stats | periodes
        self.grid_rowconfigure(1, weight=1) # buttons
        
        self.option_add('*tearOff', False)
        self.menus: MenusWidget = MenusWidget(self)
        self["menu"] = self.menus
        
        self.statsFrame: StatsFrame = StatsFrame(self)
        self.statsFrame.grid(row=0, column=0, sticky="nsew")
        
        self.periodesFrame: PerodesFrame = PerodesFrame(self)
        self.periodesFrame.grid(row=0, column=1, sticky="nsew")
        
        self.buttonsFrame: ActionsFrame = ActionsFrame(self)
        self.buttonsFrame.grid(row=1, column=0, columnspan=2, sticky="nsew")

    def updateDatas(self, targets:"set[_UpdatedTarget]")->None:
        """update everything neeeded with the new datas"""
        self.statsFrame.updatedDatas(targets)
        self.periodesFrame.updatedDatas(targets)
        self.menus.updatedDatas(targets)
    

    def isDialogRegistered(self, dialog:"PeriodeDialog")->bool:
        return self.__periodeDialogs.get(dialog.periode) is dialog

    def isPeriodeRegistered(self, elt:"Periode")->bool:
        return elt in self.__periodeDialogs.keys()

    def destroyAllRegisteredDialogs(self)->None:
        print(f"[DEBUG] destroy all")
        dialogsToRemove = list(self.__periodeDialogs.values())
        for dialog in dialogsToRemove:
            self.unregisterPeriodeDialog(dialog)
            dialog.destroy()

    def addPeriodeDialog(self, dialog:"PeriodeDialog")->None:
        print(f"[DEBUG] registering: {dialog}")
        currentDialog = self.__periodeDialogs.get(dialog.periode, None)
        if currentDialog is dialog:
            # => registering twice
            tkinter.messagebox.showerror(
                title="[BUG]", message=f"\t[BUG]\nthe dialog: {dialog}\n\t is alredy added")
        elif currentDialog is not None: 
            # => this periode alredy have a dialog
            # destroy the new window, shouldn't exist
            dialog.destroy()
            print(f"[DEBUG] registering (failed): {dialog}")
            tkinter.messagebox.showerror(
                title="impossible action", 
                message=f"can't add a new dialog: {dialog}\n on this periode (current dialog: {currentDialog})")
            currentDialog.focus()
        else: # => dialog is not unregistered, register it
            self.__periodeDialogs[dialog.periode] = dialog
    
    def destroyPeriodeDialog_perPeriode(self, periode:"Periode")->None:
        """remove and destroy the PeriodeDialog associated to the given periode\n
        raise a KeyError if the periode don't have a dialog"""
        # remove the dialog from the registered dialogs
        dialog: "PeriodeDialog|None" = self.__periodeDialogs.pop(periode, None)
        if dialog is None: 
            raise KeyError(f"the periode: {periode} don't have a {PeriodeDialog.__name__} associated")
        print(f"[DEBUG] destroying: {dialog}")
        # kill the dialog
        dialog.destroy() # kill would unregister the dialog (alredy done)
    
    def unregisterPeriodeDialog(self, dialog:"PeriodeDialog")->None:
        """unregister the dialog (don't destroy it)"""
        print(f"[DEBUG] unregistering: {dialog}")
        currentDialog = self.__periodeDialogs.get(dialog.periode, None)
        if currentDialog is dialog:
            # => everithing is correct, unregister it
            self.__periodeDialogs.pop(dialog.periode)
        else: # => this dialog isn't registered
            errorMessage = f"failed to unregister: {dialog}\n" \
                + ("no dialog" if currentDialog is None else "another") \
                +" is registered for this periode"
            tkinter.messagebox.showerror(title="[BUG] failed unregistering", message=errorMessage)
            # focus the dialog that is alredy registered
            if currentDialog is not None:
                currentDialog.focus()
            # raise an error since this shouldn't happend
            raise RuntimeError(errorMessage)
    
    
    def iconifyAll(self)->None:
        for dialog in self.__periodeDialogs.values():
            dialog.iconify()

    def deiconifyAll(self)->None:
        for dialog in self.__periodeDialogs.values():
            dialog.deiconify()

class MenusWidget(tkinter.Menu):
    def __init__(self, mainFrame:MainFrame) -> None:
        super().__init__(mainFrame)
        self.mainFrame: MainFrame = mainFrame
        self.application: App = mainFrame.application
        self.editConfigDialog:"None|EditConfigDialog" = None
        self.activitiesManager:"None|ActivitiesManager" = None
        self.exportDialog:"None|ExportDialog" = None
        self.scheduleDialog:"None|ScheduleDialog" = None
        
        # fileSubMenu
        self.fileSubMenu = tkinter.Menu(self)
        self.fileSubMenu.add_command(label="New", command=self.newDatas, accelerator="Ctrl+N")
        self.fileSubMenu.add_command(label="Open", command=self.openFromFile, accelerator="Ctrl+O")
        self.fileSubMenu.add_command(label="Save", command=self.saveToFile, accelerator="Ctrl+S")
        self.fileSubMenu.add_command(label="Save as", command=self.saveAsToFile, accelerator="Ctrl+RShift+S")
        self.fileSubMenu.add_command(label="Merge with", command=self.mergeWithFile, accelerator="Ctrl+M")
        self.fileSubMenu.add_command(label="Exit", command=self.application.exit)
        self.add_cascade(menu=self.fileSubMenu, label="File")
        # editSubMenu
        self.editSubMenu = tkinter.Menu(self)
        self.editSubMenu.add_command(label="Edit work config", command=self.startEditWorkloadConfig)
        self.editSubMenu.add_command(label="Revert last change", command=self.application.revert, accelerator="Ctrl+Z")
        self.editSubMenu.add_command(label="Eedo changes", command=self.application.redo, accelerator="Ctrl+Y")
        self.add_cascade(menu=self.editSubMenu, label="Edit")
        # ActivitiesSubMenu
        self.ActivitiesSubMenu = tkinter.Menu(self)
        self.ActivitiesSubMenu.add_command(label="Manage activities", command=self.openActivitiesManager)
        self.add_cascade(menu=self.ActivitiesSubMenu, label="Activities")
        # ExportSubMenu
        self.ExportSubMenu = tkinter.Menu(self)
        self.ExportSubMenu.add_command(label="Export periodes", command=self.openExportMenu, accelerator="Ctrl+E")
        self.ExportSubMenu.add_command(label="generate schedule", command=self.openScheduleMenu, accelerator="Ctrl+G")
        self.add_cascade(menu=self.ExportSubMenu, label="Export")
        
        # fileSubMenu
        self.mainFrame.bind("<Control-n>", func=lambda e: self.newDatas())
        self.mainFrame.bind("<Control-o>", func=lambda e: self.openFromFile())
        self.mainFrame.bind("<Control-s>", func=lambda e: self.saveToFile())
        self.mainFrame.bind("<Control-S>", func=lambda e: self.saveAsToFile())
        self.mainFrame.bind("<Control-m>", func=lambda e: self.mergeWithFile())
        # editSubMenu
        self.mainFrame.bind("<Control-z>", func=lambda e: self.application.revert())
        self.mainFrame.bind("<Control-y>", func=lambda e: self.application.redo())
        # exportSubMenu
        self.mainFrame.bind("<Control-e>", func=lambda e: self.openExportMenu())
        self.mainFrame.bind("<Control-g>", func=lambda e: self.openScheduleMenu())
    
    def newDatas(self) -> None:
        # create a new empty datas and update the datas to the app
        self.application.newEmptyDatas()
    
    def __OpenFileAndLoadDatas(self)->"FullDatas|None":
        """ask the file to open and load the datas from it"""
        # ask a file to open
        file = tkinter.filedialog.askopenfile(
            mode="rb", defaultextension=".pickle", initialdir=DATAS_DIRECTORY, 
            parent=self, filetypes=DATAS_FILE_TYPES, title="select the datas file to open")
        if file is None: # => no file selected, don't open anything
            return None
        assert isinstance(file, BufferedReader)
        # read the datas in it and update the datas to the app
        with file:
            return FullDatas.fromFile(file)
    
    def openFromFile(self) -> None:
        # ask to save the current datas (so you don't loose your datas ^^)
        saveResponse = self.application.askToSave()
        if saveResponse == "canceled": 
            return None
        newDatas: "FullDatas|None" = self.__OpenFileAndLoadDatas()
        if newDatas is None:
            return None # no datas loaded
        self.application.useDatas(newDatas, saveResponse)
        
    def mergeWithFile(self)->None:
        newDatas: "FullDatas|None" = self.__OpenFileAndLoadDatas()
        if newDatas is None:
            return None # no datas loaded
        # merge the current datas with the new datas
        updates = self.application.datas.mergeDatasWith(newDatas)
        self.application.updatedDatas(updates)
    
    def saveToFile(self)->bool:
        """save the datas (ask a file if it don't have one) and return whether the datas was saved"""
        filePath: "Path|None" = self.application.datas.getSavePath()
        if filePath is None: 
            # => don't have a save path => ask for it
            return self.saveAsToFile() # finished
        # => have a file
        if self.application.datas.isSaved():
            # => alredy saved
            tkinter.messagebox.showinfo(title="save info", message="alredy saved '~'")
            return True 
        print("[DEBUG] true saved datas @ saveToFile")
        return self.application.safeSaveToFile(datas=None, filePath=filePath)
    
    def saveAsToFile(self)->bool:
        """ask a file to save the datas and return whether the datas was saved"""
        # ask a file for saving 
        filePath: "Path|None" = self.application.askFilenameToSaveDatas(master=self)
        print("[DEBUG] save filename:", filePath)
        if filePath is None: # => no file selected, don't save anything
            return False
        print("[DEBUG] true saved datas @ saveAsToFile")
        return self.application.safeSaveToFile(datas=None, filePath=filePath)
    

    def startEditWorkloadConfig(self)->None:
        if self.editConfigDialog is not None:
            tkinter.messagebox.showinfo(
                title="config editor alredy opened", 
                message="the config editor is alredy opened")
            self.editConfigDialog.focus()
        else: # => not opened => open a new one
            self.editConfigDialog = EditConfigDialog(self)
    
    def openActivitiesManager(self)->None:
        if self.activitiesManager is not None:
            tkinter.messagebox.showinfo(
                title="manager alredy opened", 
                message="the activities manager is alredy opened")
            self.activitiesManager.focus()
        else: # => not opened => open a new one
            self.activitiesManager = ActivitiesManager(self)

    def openExportMenu(self)->None:
        if self.exportDialog is not None:
            tkinter.messagebox.showinfo(
                title="exporter alredy opened", 
                message="the export menu is alredy opened")
            self.exportDialog.focus()
        else: # => not opened => open a new one
            self.exportDialog = ExportDialog(self)

    def openScheduleMenu(self)->None:
        if self.scheduleDialog is not None:
            tkinter.messagebox.showinfo(
                title="schedule generator alredy opened", 
                message="the schedule generator menu is alredy opened")
            self.scheduleDialog.focus()
        else: # => not opened => open a new one
            self.scheduleDialog = ScheduleDialog(self)

    def updatedDatas(self, targets:"set[_UpdatedTarget]")->None:
        if self.activitiesManager is not None:
            self.activitiesManager.updatedDatas(targets)
        if self.exportDialog is not None:
            self.exportDialog.updatedDatas(targets)
        # the editConfigDialog don't need to be updated
        # (ensure it don't have an updatedDatas methode)
        assert hasattr(self.editConfigDialog, "updatedDatas") is False
        


class StatsFrame(tkinter.Frame):
    
    def __init__(self, mainFrame:MainFrame) -> None:
        self.mainFrame: MainFrame = mainFrame
        self.application: App = mainFrame.application
        super().__init__(mainFrame, bg="orangered1")
        # create the widgets for each stats
        self.statLines: "list[StatLine]" = [
            ### global stats
            StatLine(self, "-"*5+"global stats"+"-"*5, lambda: "-"*25, updateConditions=_UpdatedALLTarget),
            StatLine(self, "total time done: ", self.getText_totalTime, 
                     updateConditions={"periodes", "clockin"}, autoUpdateDelay=15.0),
            StatLine(self, "average time per interval: ", self.getText_averageTimePerInterval,
                     updateConditions={"periodes", "clockin", "selectedTimeFrame"}, autoUpdateDelay=15.0),
            StatLine(self, "clocked in at: ", self.getText_clockedInAt, updateConditions={"clockin"}),
            StatLine(self, "time since clocked in: ", self.getText_timeSinceClockedIn,
                     updateConditions={"clockin"}, autoUpdateDelay=1.0),
            ### selected interval stats
            StatLine(self, "-"*5+"interval stats"+"-"*5, lambda: "-"*25, updateConditions=_UpdatedALLTarget),
            StatLine(self, "total time this interval: ", lambda: self.getText_totalTimeOverThisInterval(timeFrame=None),
                     updateConditions={"periodes", "clockin", "selectedTime", "selectedTimeFrame"}, autoUpdateDelay=15.0),
            ### target stats
            StatLine(self, "-"*5+"interval stats"+"-"*5, lambda: "-"*25, updateConditions=_UpdatedALLTarget),
            StatLine(self, "time target: ", self.getText_targtedTime, updateConditions={"config"}),
            StatLine(self, "remaining time to target: ", self.getText_remainigTimeToDo,
                     updateConditions={"periodes", "clockin", "selectedTime", "config"}, autoUpdateDelay=15.0),
            StatLine(self, "accumulated delta time to target:\n(of past intervals)", self.getText_accumulatedDeltaToTarget,
                     updateConditions={"periodes", "selectedTime", "config"}, autoUpdateDelay=15.0),
        ]
        # place each stat line
        self.grid_columnconfigure(0, weight=1)
        for row, statLine in enumerate(self.statLines):
            statLine.grid(column=0, row=row, sticky="we")
        
    
    def getText_totalTime(self)->str:
        # get the total time over all weeks and convert it to text (pretty formting to hours-minutes)
        return prettyTimedelta(self.application.datas.cumulatedDuration("all"))
    
    def getText_totalTimeOverThisInterval(self, timeFrame:"_TimeFrame|None")->str:
        # get the total time over the selected interval and convert it to text (pretty formting to hours minutes)
        selectedTimeID: _TimeID = self.application.datas.get_TimeID(selectedTime=None, selectedTimeFrame=timeFrame)
        return prettyTimedelta(self.application.datas.cumulatedDuration(selectedTimeID))

    def getText_targtedTime(self)->str:
        # get the weekly targeted time and convert it to text (pretty formting to hours minutes)
        timeTarget: "TimeTarget" = self.application.datas.getTimeTarget()
        targetedTimeFrame: "_TimeFrame" = timeTarget.timeFrame
        timeframe_text: str 
        if isinstance(targetedTimeFrame, str):
            timeframe_text = targetedTimeFrame
        else: # => selectedTimeFrame is a _TimeID
            timeframe_text = f"time frame\n{prettyTimeFrame(targetedTimeFrame)}"
        return f"{str(timeTarget.targetedTime)} per {timeframe_text}"
        
    def getText_averageTimePerInterval(self)->str:
        # get the per timeframe average time and convert it to text (pretty formting to hours minutes)
        avgTimeText:str = prettyTimedelta(self.application.datas.averageTimePer_TimeFrame(selectedTimeFrame=None))
        selectedTimeFrame: "_TimeFrame" = self.application.datas.getSelectedTimeFrame()
        timeframe_text: str 
        if isinstance(selectedTimeFrame, str):
            timeframe_text = selectedTimeFrame
        else: # => selectedTimeFrame is a _TimeID
            timeframe_text = f"time frame\n{prettyTimeFrame(selectedTimeFrame)}"
        return f"{avgTimeText} per {timeframe_text}"

    def getText_remainigTimeToDo(self)->str:
        deltaToTarget: timedelta = self.application.datas.getDeltaToTargtedTime()
        if deltaToTarget <= timedelta(0):
            # => all targetd time done
            return f"finished and {prettyTimedelta(-deltaToTarget)} over the target"
        # => still some time to do
        return f"{prettyTimedelta(deltaToTarget)} under the target"

    def getText_accumulatedDeltaToTarget(self)->str:
        accumulatedDelta: timedelta = self.application.datas.getAccumulatedDeltaToTargtedTime()
        if accumulatedDelta <= timedelta(0):
            # => all targetd time done
            return f"{prettyTimedelta(-accumulatedDelta)} over the target"
        # => still some time to do
        return f"{prettyTimedelta(accumulatedDelta)} under the target"

    def getText_clockedInAt(self)->str:
        clockinTime: "datetime|None" = self.application.datas.getClockinTime()
        if clockinTime is None:
            return "not clocked in"
        # => has clocked in
        if datetime.now().date() == clockinTime.date():
            # => same day
            return prettyDatetime(clockinTime, format="time")
        return prettyDatetime(clockinTime, format="full")

    def getText_timeSinceClockedIn(self)->str:
        timeClocked: "timedelta|None" = self.application.datas.timeSinceClockedIn()
        return ("not clocked in" if timeClocked is None else prettyTimedelta(timeClocked))
    
    def updatedDatas(self, targets:"set[_UpdatedTarget]")->None:
        """update everything neeeded with the new datas"""
        for statLine in self.statLines:
            statLine.autoUpdate(targets)




class StatLine(tkinter.Frame):
    def __init__(self, master:tkinter.Widget, fixedText:str, statTextGetter:"Callable[[], str]",
                 updateConditions:"set[_UpdatedTarget]", *, autoUpdateDelay:"float|None"=None) -> None:
        # set the attributs
        self.master: tkinter.Widget = master
        super().__init__(master=master, bg="palegreen")
        self.__autoUpdateDelay: "float|None" = autoUpdateDelay
        self.__scheduledAutoUpdate: "str|None" = None
        """str -> the id of the scheduled .after(...) call | None -> nothing scheduled"""
        self.__updateConditions: "set[_UpdatedTarget]" = updateConditions
        """the conditions that trigger an update (an update target that is not in it => no update)"""
        
        self.fixedText: str = fixedText
        self.statTextGetter: "Callable[[], str]" = statTextGetter
        
        # create the widgets
        self.fixedLabel = tkinter.Label(self, text=self.fixedText, bg="cyan")
        self.statLabel = tkinter.Label(self, text="Not Setted", bg="yellow")
        
        # configur widgets placement
        #self.grid_columnconfigure(0, weight=len(self.fixedText))
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0)
        self.fixedLabel.grid(column=0, row=0, sticky="w")
        self.statLabel.grid(column=1, row=0, sticky="e")
        self.autoUpdate(self.__updateConditions)

    ### auto update related
    
    def autoUpdate(self, targets:"set[_UpdatedTarget]")->None:
        """update the text and schedule next update if needed"""
        if targets.isdisjoint(self.__updateConditions):
            return None # the condition to update are not meets
        self.__unScheduleUpdate()
        self.__updateStatText()
        self.__scheduleUpdate()
    
    def __updateStatText(self) -> None:
        # get the new stat text
        newStatText = self.statTextGetter()
        # update the widget with the new text
        self.statLabel["text"] = newStatText
        # self.grid_columnconfigure(1, weight=len(newStatText))
    
    @property
    def autoUpdateDelay(self)->"float|None":
        return self.__autoUpdateDelay

    def setAutoUpdateDelay(self, *, newValue:"float|None", updateNow:bool)->None:
        if self.__autoUpdateDelay == newValue:
            # => same value => alredy done
            return None
        # => different value
        self.__autoUpdateDelay = newValue
        if updateNow is True:
            self.autoUpdate(self.__updateConditions)
        else: self.__scheduleUpdate()
        
    def __scheduleUpdate(self)->None:
        """schedule next update (if needed)"""
        if self.__autoUpdateDelay is None:
            return None # => don't re auto update
        self.__scheduledAutoUpdate = \
            self.after(int(self.__autoUpdateDelay * 1000),
                       lambda: self.autoUpdate(self.__updateConditions))
    
    def __unScheduleUpdate(self)->None:
        """un schedule current (if exist)"""
        if self.__scheduledAutoUpdate is not None:
            self.after_cancel(self.__scheduledAutoUpdate)
            self.__scheduledAutoUpdate = None


class PerodesFrame(tkinter.Frame):
    def __init__(self, mainFrame:MainFrame) -> None:
        super().__init__(mainFrame, bg="green")
        self.mainFrame: MainFrame = mainFrame
        self.application: App = mainFrame.application
        
        # create the widgets 
        self.timeFrameSelector = TimeFrameSelectorLine_selectedTimeFrame(
            self, self.application, "select the time frame: ", selectFunction=self.selectTimeFrame)
        self.selectedTimeIDStatLine: StatLine = \
            StatLine(self, "selected interval: ", self.get_selected_TimeID_Text, 
                     updateConditions={"selectedTime", "selectedTimeFrame"})
        self.periodesTable: PeriodeTable = PeriodeTable(self)
        
        # place the widgets
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=0) # select timeframe
        self.grid_rowconfigure(1, weight=0) # selected timeID
        self.grid_rowconfigure(2, weight=1) # periodes table
        self.timeFrameSelector.grid(column=0, row=0, sticky="we")
        self.selectedTimeIDStatLine.grid(column=0, row=1, sticky="we")
        self.periodesTable.grid(column=0, row=2, sticky="nswe")
        
    
    def get_selected_TimeID_Text(self) -> str:
        # get the selected _TimeID 
        selectedTimeID: _TimeID = self.application.datas.get_TimeID(selectedTime=None, selectedTimeFrame=None)
        return selectedTimeID.prettyText()

    def selectTimeFrame(self, timeFrame:"_TimeFrame")->None:
        self.application.updatedDatas(
            self.application.datas.selectTimeFrame(timeFrame))

    def updatedDatas(self, targets:"set[_UpdatedTarget]")->None:
        """update everything neeeded with the new datas"""
        self.timeFrameSelector.updatedDatas(targets)
        self.selectedTimeIDStatLine.autoUpdate(targets)
        self.periodesTable.updatedDatas(targets)



class GenericSortableTableFrame(tkinter.Frame, ABC, Generic[_T_TableColumn, _T_TableElement]):
    @property
    @abstractmethod
    def COLUMNS(self)->"tuple[_T_TableColumn, ...]":
        raise NotImplementedError
    
    def __init__(self, master:tkinter.Misc, application:App)->None:
        super().__init__(master=master)
        self.application: App = application
        self.currentSortStatus:"tuple[_T_TableColumn, bool]" = (self.COLUMNS[0], True)
        """the sorting currently used (targeted col, True|False -> asc|dsc)"""
        
        self.table = tkinter.ttk.Treeview(self, columns=self.COLUMNS, show="headings")
        self.scrollbar = tkinter.ttk.Scrollbar(self, orient="vertical", command=self.table.yview)
        self.table.configure(yscrollcommand=self.scrollbar.set)
        
        for columnName in self.COLUMNS:
            self.table.heading(columnName, text=columnName, anchor="center", 
                                         command=functools.partial(self.toogleSorting, columnName))
            self.table.column(columnName, width=0, anchor="center")
        
        self.grid_rowconfigure(0, weight=1) # => use full vertical space
        self.grid_columnconfigure(0, weight=1) # table
        self.grid_columnconfigure(1, weight=0) # scroll bar
        self.table.grid(row=0, column=0, sticky="nswe")
        self.scrollbar.grid(row=0, column=1, sticky="nsw")
        
    def toogleSorting(self, targetedColumn:"_T_TableColumn")->None:
        # => cycle (asc -> dsc -> asc -> ...) or change the column
        (currColumn, currState) = self.currentSortStatus
        # if it is the same column filp the state, if use asc order
        nextState:bool = (True if (currColumn != targetedColumn) else (not currState))
        self.currentSortStatus = (targetedColumn, nextState)
        self.sortLines()
    
    def sortLines(self)->None:
        """sort the lines based on the currentSortStatus"""
        self.table.delete(*self.table.get_children())
        # add the activities
        for element in self.getSortedElements():
            self.addTableLine(element)
    
    def addTableLine(self, element:"_T_TableElement")->None:
        elementDatas: "dict[_T_TableColumn, str]" = \
            self.getElementDatas(element)
        # ensure the columns are here
        assert set(elementDatas.keys()) == set(self.COLUMNS)
        # insert the datas in the table
        self.table.insert(
            "", tkinter.END, values=[elementDatas[col] for col in self.COLUMNS],
            tags=self.getElementTags(element))
    
    @abstractmethod
    def getElementTags(self, element:"_T_TableElement")->"tuple[str, ...]":
        raise NotImplementedError
    
    @abstractmethod
    def getElementDatas(self, element:"_T_TableElement")->"dict[_T_TableColumn, str]":
        raise NotImplementedError
    
    @abstractmethod
    def getSortedElements(self)->"list[_T_TableElement]":
        raise NotImplementedError
    
    

class PeriodeTable(GenericSortableTableFrame[_PeriodeColumn, Periode]):
    COLUMNS: "tuple[_PeriodeColumn, ...]" = get_args(_PeriodeColumn)
    UPDATE_CONDITIONS: "set[_UpdatedTarget]" = {"periodes", "selectedTime", "selectedTimeFrame"}
    
    def __init__(self, perodesFrame:PerodesFrame) -> None:
        super().__init__(perodesFrame, perodesFrame.application)
        self.perodesFrame: PerodesFrame = perodesFrame
        self.__subPeriodes: "PeriodesStorage[_TimeID]" # setted in self.updatedDatas()
        
        self.table.bind("<Double-1>", self.onDoubleClick)
        self.updatedDatas(self.UPDATE_CONDITIONS)
    
    @override
    def getSortedElements(self)->"list[Periode]":
        sortCol, order = self.currentSortStatus
        return self.__subPeriodes.getPeriodes_sortedByfield(
            _PeriodeColumn_TO_PeriodeField[sortCol], order)
    
    @override
    def getElementDatas(self, element: Periode)->"dict[_PeriodeColumn, str]":
        return {
            "start date": prettyDatetime(element.startTime, format="full"),
            "end date": prettyDatetime(element.endTime, format="full"),
            "duration": element.prettyDuration(),
            "activity": str(element.activity),
        }
    
    @override
    def getElementTags(self, element:"Periode")->"tuple[str, ...]":
        return (str(datetimeToText(element.startTime)), )

    def updatedDatas(self, targets:"set[_UpdatedTarget]")->None:
        if targets.isdisjoint(self.UPDATE_CONDITIONS):
            return None # => none of the requirements are meeted
        # => at least one of the updatedtarget is in the conditions
        # clear the dialogs of the previous periodes
        try: dialogesToRemove: "list[Periode]" = [periode for periode in self.__subPeriodes]
        except AttributeError: pass # => self.__subPeriodes not setted
        else: # => dialogs to remove
            for periode in dialogesToRemove:
                try: self.application.tkinterRoot.\
                    destroyPeriodeDialog_perPeriode(periode)
                except KeyError: pass # => didn't had a dialog
        # get the new periodes
        self.__subPeriodes = \
            self.application.datas.getPeriodes(selectedTime=None, selectedTimeFrame=None)
        # generate the sorted lines
        self.sortLines()

    def onDoubleClick(self, event:"tkinter.Event")->None:
        # ge the seleected item
        selection: "tuple[str, ...]" = self.table.selection()
        if len(selection) != 1: 
            return None # => not a single item selected
        item: str = selection[0]
        # get the clicked periode
        startTime: datetime = datetimeFromText(self.table.item(item, "tags")[0])
        periode: "Periode|None" = self.__subPeriodes.getPeriode(startTime=startTime)
        assert periode is not None, ValueError("there is a bug, the periode sould be inside the sub storage")
        # open the edit menu for this periode
        self.application.tkinterRoot.addPeriodeDialog(EditPeriodeDialog(self, self.application, periode))






class WidgetsLine(tkinter.Frame):
    def __init__(self, master:tkinter.Misc, application:App,
                 ) -> None:
        super().__init__(master, bg="lightgoldenrod1")
        self.master: tkinter.Misc = master
        self.application: App = application
        self.buttons: "list[tkinter.Widget]" = []
        
    def addWidgets(self, buttons:"list[tkinter.Widget]")->None:
        self.buttons.extend(buttons)
    
    def placeButtons(self, packing: "Literal['grid', 'pack']")->None:
        for index, button in enumerate(self.buttons):
            assert button.master == self
            if packing == "pack":
                button.pack(side=tkinter.LEFT)
            elif packing == "grid":
                button.grid(column=index, row=0, sticky="we")
            else: raise ValueError(f"invalide packing methode: {packing}")
        

class ActionsFrame(tkinter.Frame):
    def __init__(self, mainFrame:MainFrame) -> None:
        super().__init__(mainFrame, bg="orange")
        self.mainFrame: MainFrame = mainFrame
        self.application: App = mainFrame.application
        
        # create the buttons
        btnFont = self.mainFrame.fonts.big
        padX, padY = (5, 15)
        self.buttonsLine1 = WidgetsLine(self, self.application)
        self.buttonsLine1.addWidgets([
            tkinter.Button(self.buttonsLine1, text="add periode", bg="lightpink",
                padx=padX*10, pady=padY, command=self.addPeriode, font=btnFont),
            tkinter.Button(self.buttonsLine1, text="remove periode", bg="lightpink",
                padx=padX, pady=padY, command=self.removePeriode, font=btnFont),
        ])
        self.buttonsLine2 = WidgetsLine(self, self.application)
        self.buttonsLine2.addWidgets([
            tkinter.Button(self.buttonsLine2, text="go to previous interval", bg="lightpink", 
                padx=padX, pady=padY, command=self.selectPrev, font=btnFont), 
            tkinter.Button(self.buttonsLine2, text="go to now", bg="lightpink", 
                padx=padX, pady=padY, command=self.selectNow, font=btnFont), 
            tkinter.Button(self.buttonsLine2, text="go to next interval", bg="lightpink", 
                padx=padX, pady=padY, command=self.selectNext, font=btnFont), 
        ])
        self.buttonsLine3 = WidgetsLine(self, self.application)
        self.buttonsLine3.addWidgets([
            tkinter.Button(self.buttonsLine3, text="clock in", bg="lightpink", 
                padx=padX, pady=padY, command=self.clockIn, font=btnFont), 
            tkinter.Button(self.buttonsLine3, text="clock out", bg="lightpink", 
                padx=padX, pady=padY, command=self.clockOut, font=btnFont),
            tkinter.Button(self.buttonsLine3, text="revert clock in", bg="lightpink", 
                padx=padX, pady=padY, command=self.unClockIn, font=btnFont), 
        ])
        
        self.mainFrame.bind("<Prior>", self.selectPrev) # Page down
        self.mainFrame.bind("<Next>", self.selectNext) # Page Up
        self.mainFrame.bind("<End>", self.selectEnd)
        self.mainFrame.bind("<Home>", self.selectStart)
        
        # place the buttons
        self.buttonsLine1.placeButtons(packing="grid")
        self.buttonsLine2.placeButtons(packing="grid")
        self.buttonsLine3.placeButtons(packing="grid")
        self.buttonsLine1.pack(side=tkinter.TOP)
        self.buttonsLine2.pack(side=tkinter.TOP)
        self.buttonsLine3.pack(side=tkinter.TOP)

    def selectPrev(self, event:"tkinter.Event|None"=None)->None:
        self.application.updatedDatas(self.application.datas.goToPrev_TimeFrame())
    
    def selectNext(self, event:"tkinter.Event|None"=None)->None:
        self.application.updatedDatas(self.application.datas.goToNext_TimeFrame())
        
    def selectEnd(self, event:"tkinter.Event|None"=None)->None:
        self.application.updatedDatas(self.application.datas.goToLast_TimeFrame())
    
    def selectStart(self, event:"tkinter.Event|None"=None)->None:
        self.application.updatedDatas(self.application.datas.goToFirst_TimeFrame())

    def selectNow(self, event:"tkinter.Event|None"=None)->None:
        self.application.updatedDatas(self.application.datas.goToNow())

    def __createEmptyPeriode(self)->Periode:
        now = datetime.now()
        return Periode(startTime=now, endTime=now+timedelta(seconds=1), activity=None, comments=None)

    def addPeriode(self, event:"tkinter.Event|None"=None)->None:
        # start a dialog to add a periode
        periode: Periode = self.__createEmptyPeriode()
        self.application.tkinterRoot.addPeriodeDialog(AddPeriodeDialog(self, self.application, periode))
    
    def removePeriode(self, event:"tkinter.Event|None"=None)->None:
        # start a dialog to remove a periode
        periode: Periode = self.__createEmptyPeriode()
        self.application.tkinterRoot.addPeriodeDialog(RemovePeriodeDialog(self, self.application, periode))

    def clockIn(self, event:"tkinter.Event|None"=None):
        # clock in and update the app
        with ErrorHandlerWithMessage("failed to clock in", self):
            self.application.datas.clockin()
        self.application.updatedDatas({"clockin"})
        
    def clockOut(self, event:"tkinter.Event|None"=None):
        # ge the clocked periode
        with ErrorHandlerWithMessage("failed to clock out", self):
            clockedPeriode: Periode = self.application.datas.clockout()
        # start a dialog to add this periode
        self.application.updatedDatas({"clockin"})
        self.application.tkinterRoot.addPeriodeDialog(AddPeriodeDialog(self, self.application, clockedPeriode))
        
    def unClockIn(self, event:"tkinter.Event|None"=None):
        with ErrorHandlerWithMessage("failed to un-clock in", self):
            self.application.datas.unClockin()
        self.application.updatedDatas({"clockin"})




class CustomTopLevel(tkinter.Toplevel):
    def __init__(self, master:tkinter.Misc, application:App, title:str,
                 resizeable:bool=False, posDelta:"tuple[int, int]"=(100, 100))->None:
        super().__init__(master=master, bg="lightskyblue")
        self.title(title)
        self.application: App = application
        self.resizable(resizeable, resizeable)
        # determine the position of the 
        selfX = self.master.winfo_x() + posDelta[0]
        selfY = self.master.winfo_y() + posDelta[1]
        self.geometry(f"+{selfX}+{selfY}")


class SupportEditConfigLine(Protocol):
    fieldName: "_ConfigField"
    def getEntryText(self)->str: ...
    def grid_configure(self, *, column:int=..., columnspan:int=...,
                       row:int=..., rowspan:int=..., sticky:str=...)->None: ...
 

class EditConfigDialog(CustomTopLevel):
    def __init__(self, menusWidget:MenusWidget) -> None:
        super().__init__(menusWidget, menusWidget.application, title="config editor")
        self.menusWidget: MenusWidget = menusWidget
        
        self.entryLines:"list[SupportEditConfigLine]" = [
            TextEntryLine_config(self, self.application, "name of the configuration: ", fieldName="name"),
            TextEntryLine_config(self, self.application, "description the configuration: ", fieldName="description"),
            TextEntryLine_config(self, self.application, "targeted time to do per periode: ", fieldName="targetedTime"),
            TimeFrameSelectorLine_configField(self, self.application, "time frame to do the targeted time: "),
        ]
        self.validateButton = tkinter.Button(self, text="validate", bg="maroon1", command=self.saveConfig)
        
        # place each entry line
        self.grid_columnconfigure(0, weight=1)
        for row, entryLine in enumerate(self.entryLines):
            entryLine.grid_configure(column=0, row=row, sticky="we")
        self.validateButton.grid(column=0, row=len(self.entryLines), sticky="we")
        
    def __getConfigDatas(self)->"dict[_ConfigField, str]":
        return {entryLine.fieldName: entryLine.getEntryText()
                for entryLine in self.entryLines}
    
    @override
    def destroy(self)->None:
        """unbind it and destroy the window"""
        self.menusWidget.editConfigDialog = None
        super().destroy()
    
    def saveConfig(self)->None:
        # get the new Configuration
        # swap the config in the datas with the new one and update the app
        self.application.updatedDatas(
            self.application.datas.editConfig(self.__getConfigDatas()))
        self.destroy()
    

class TextEntryLine(tkinter.Frame):
    def __init__(self, master:tkinter.Misc, application: App, 
                 fixedText:str, defaultEntryText:str) -> None:
        # set the attributs
        self.master: tkinter.Misc = master
        self.application: App = application
        super().__init__(self.master, bg="lightskyblue")
        
        self.fixedText: str = fixedText
        self.var = tkinter.StringVar(self, value=defaultEntryText)
        
        # create the widgets
        self.fixedLabel = tkinter.Label(self, text=self.fixedText, bg="cyan")
        self.entryLabel = tkinter.Entry(self, textvariable=self.var, bg="yellow")
        
        # configur widgets placement
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=0) # start
        self.fixedLabel.grid(column=0, row=0, sticky="w")
        self.entryLabel.grid(column=1, row=0, sticky="w")
        
    def getEntryText(self)->str:
        return self.var.get()


class TextEntryLine_config(TextEntryLine):
    def __init__(self, master:tkinter.Misc, application: App, 
                 fixedText:str, fieldName:"_ConfigField") -> None:
        self.fieldName: "_ConfigField" = fieldName
        super().__init__(
            master=master, application=application, fixedText=fixedText,
            defaultEntryText=application.datas.getConfigText(fieldName))


class TextEntryLine_periode(TextEntryLine):
    def __init__(self, master:tkinter.Misc, application: App,
                 periode: Periode, fixedText:str, fieldName:"_PeriodeField") -> None:
        self.fieldName: "_PeriodeField" = fieldName
        self.periode: Periode = periode
        super().__init__(
            master=master, application=application, fixedText=fixedText,
            defaultEntryText=self.periode.getFieldToStr(fieldName))

    def updatedDatas(self, targets:"set[_UpdatedTarget]")->None:
        pass # nothing to update


class ComboboxLine(ABC, tkinter.Frame):
    def __init__(self, master:tkinter.Misc, application: App, 
                 fixedText:str, defaultValue:str, ) -> None:
        # set the attributs
        self.master: tkinter.Misc = master
        self.application: App = application
        super().__init__(self.master, bg="lightskyblue")
        
        self.fixedText: str = fixedText
        self.var = tkinter.StringVar(self, value=defaultValue)
        
        # create the widgets
        self.fixedLabel = tkinter.Label(self, text=self.fixedText, bg="cyan")
        self.comboBox = tkinter.ttk.Combobox(self, textvariable=self.var, values=[])
        
        # configur widgets placement
        self.grid_columnconfigure(0, weight=1) # label
        self.grid_columnconfigure(1, weight=0) # comboBox
        self.fixedLabel.grid(column=0, row=0, sticky="w")
        self.comboBox.grid(column=1, row=0, sticky="e")
        
    def getEntryText(self)->str:
        return self.var.get()
    
    def setValues(self, values:"list[str]")->None:
        self.comboBox["values"] = values
    
    @abstractmethod
    def updatedDatas(self, targets:"set[_UpdatedTarget]")->None:
        """update everything neeeded with the new datas"""

class ActivitySelectorLine(ComboboxLine):
    UPDATE_CONDITIONS: "set[_UpdatedTarget]" = {"activity"}
    def __init__(self, master:tkinter.Misc, application: App, 
                 fixedText:str, defaultActivity:"Activity|None") -> None:
        if defaultActivity is None: defaultActivity = Activity(None)
        super().__init__(
            master, application, fixedText, defaultValue=str(defaultActivity))
        self.fieldName: "_PeriodeField" = "activity" # for SupportPeriodeFieldEntry
        self.updatedDatas(self.UPDATE_CONDITIONS)
    
    @override
    def updatedDatas(self, targets:"set[_UpdatedTarget]")->None:
        if self.UPDATE_CONDITIONS.isdisjoint(targets):
            return None # => condition not meets
        self.setValues(list(map(str, self.application.datas.getRegisteredActivites())))
        

class TimeFrameSelectorLine(ComboboxLine):
    UPDATE_CONDITIONS: "set[_UpdatedTarget]" = {"selectedTimeFrame"}
    def __init__(self, master:tkinter.Misc, application: App, 
                 fixedText:str, selectFunction:"Callable[[_TimeFrame], None]") -> None:
        self.application = application
        super().__init__(
            master, application, fixedText, 
            defaultValue=timeFrameToText(self.getDefaultTimeFrame()))
        self.__selectFunction: "Callable[[_TimeFrame], None]" = selectFunction
        self.selectButton = tkinter.Button(
            self, text="select", bg="maroon1", command=self.selectTimeFrame)
        self.selectButton.grid(column=2, row=0, sticky="e")
        self.updatedDatas(self.UPDATE_CONDITIONS)
    
    @abstractmethod
    def getDefaultTimeFrame(self)->"_TimeFrame":
        raise NotImplementedError("must be implemented by the sub classes")
    
    @override
    def updatedDatas(self, targets:"set[_UpdatedTarget]")->None:
        if self.UPDATE_CONDITIONS.isdisjoint(targets):
            return None # => condition not meets
        defaultTimeFrame = self.getDefaultTimeFrame()
        defaultTimeFrame_text: str = timeFrameToText(
            self.application.datas.get_TimeID(None, selectedTimeFrame=defaultTimeFrame))
        self.comboBox.configure(width=len(defaultTimeFrame_text))
        self.setValues([defaultTimeFrame_text, *get_args(_TimeFrame_literals)])
        self.var.set(defaultTimeFrame_text)
        
    def getTimeFrame(self)->"_TimeFrame":
        with ErrorHandlerWithMessage("invalide timeframe", self):
            return timeFrameFromText(self.getEntryText())
    
    def selectTimeFrame(self)->None:
        self.__selectFunction(self.getTimeFrame())


class TimeFrameSelectorLine_selectedTimeFrame(TimeFrameSelectorLine):
    def __init__(self, master:tkinter.Misc, application:App,
                 fixedText:str, selectFunction:"Callable[[_TimeFrame], None]")->None:
        super().__init__(master, application, fixedText, selectFunction)
    @override
    def getDefaultTimeFrame(self)->"_TimeFrame":
        return self.application.datas.getSelectedTimeFrame()

class TimeFrameSelectorLine_configField(TimeFrameSelectorLine):
    def __init__(self, master:tkinter.Misc, application:App, fixedText:str)->None:
        self.fieldName: "_ConfigField" = "targetedTimeFrame"
        super().__init__(master, application, fixedText, lambda _: None)
    @override
    def getDefaultTimeFrame(self)->"_TimeFrame":
        return timeFrameFromText(self.application.datas.getConfigText(self.fieldName))



class SupportPeriodeFieldEntry(Protocol):
    fieldName: "_PeriodeField"
    def getEntryText(self)->str: ...
    def grid_configure(self, *, column:int=..., columnspan:int=...,
                       row:int=..., rowspan:int=..., sticky:str=...)->None: ...
    def updatedDatas(self, targets:"set[_UpdatedTarget]")->None: ...

class PeriodeDialog(CustomTopLevel):
    def __init__(self, master:tkinter.Misc, application:App, periode:Periode) -> None:
        super().__init__(master, application, "periode editor")
        self.periode: Periode = periode

        
        self.entryLines:"list[SupportPeriodeFieldEntry]" = [
            TextEntryLine_periode(self, self.application, self.periode, "start of the periode: ", fieldName="startTime"),
            TextEntryLine_periode(self, self.application, self.periode, "end of the periode: ", fieldName="endTime"),
            ActivitySelectorLine(self, self.application, "activity done: ", defaultActivity=self.periode.activity),
            TextEntryLine_periode(self, self.application, self.periode, "comments: ", fieldName="comments"),
        ]
        self.nbEntrys:int = len(self.entryLines)
        
        # place each entry line
        self.grid_columnconfigure(0, weight=1)
        for row, entryLine in enumerate(self.entryLines):
            entryLine.grid_configure(column=0, row=row, sticky="we")
        
    
    def getPeriode(self)->"Periode":
        periodeText:"dict[_PeriodeField, str]" = {
            entryLine.fieldName : entryLine.getEntryText()
            for entryLine in self.entryLines
        }
        return Periode.fromText(**periodeText)
    
    @override
    def destroy(self)->None:
        """unbind it and destroy the window"""
        if self.application.tkinterRoot.isDialogRegistered(self):
            self.application.tkinterRoot.unregisterPeriodeDialog(self)
        super().destroy()
    
    def _updateAndKill(self, targets:"set[_UpdatedTarget]")->None:
        # kill the window
        self.destroy()
        # update the datas
        self.application.updatedDatas(targets)


class EditPeriodeDialog(PeriodeDialog):
    
    def __init__(self, master: tkinter.Misc, application: App, periode: Periode) -> None:
        super().__init__(master, application, periode)
        self.splitPeriodeDialog: "SplitPeriodeDialog|None" = None
        
        self.removeButton = tkinter.Button(
            self, text="remove this periode", bg="lightsalmon1", command=self.removePeriode)
        self.splitButton = tkinter.Button(
            self, text="split the periode", bg="lightsalmon1", command=self.splitPeriode)
        self.validateButton = tkinter.Button(
            self, text="validate changes", bg="maroon1", command=self.savePeriode)
        self.removeButton.grid(column=0, row=self.nbEntrys, sticky="we")
        self.splitButton.grid(column=0, row=self.nbEntrys+1, sticky="we")
        self.validateButton.grid(column=0, row=self.nbEntrys+2, sticky="we")

    def removePeriode(self)->None:
        # remove the current periode, update the datas and kill the window
        self._updateAndKill(self.application.datas.substractPeriode(self.periode))
    
    def savePeriode(self)->None:
        # remove the current periode and add the new periode
        with ErrorHandlerWithMessage("couldn't add the periode", self):
            updates = self.application.datas.replacePeriodes(
                oldPeriode=self.periode, newPeriodes=[self.getPeriode()])
        # update the datas and kill the window
        self._updateAndKill(updates)

    def splitPeriode(self)->None:
        if self.splitPeriodeDialog is not None:
            tkinter.messagebox.showerror("impossible action", "a dialog window is alredy oppened to split this periode")
            return None
        self.splitPeriodeDialog = SplitPeriodeDialog(self)
    
    @override
    def iconify(self)->None:
        super().iconify()
        if self.splitPeriodeDialog is not None:
            self.splitPeriodeDialog.iconify()
    
    @override
    def deiconify(self)->None:
        super().deiconify()
        if self.splitPeriodeDialog is not None:
            self.splitPeriodeDialog.focus()

class AddPeriodeDialog(PeriodeDialog):
    
    def __init__(self, master: tkinter.Misc, application: App, periode: Periode) -> None:
        super().__init__(master, application, periode)
        self.addButton = tkinter.Button(self, text="add periode", bg="maroon1", command=self.addPeriode)
        self.addButton.grid(column=0, row=self.nbEntrys+1, sticky="we")
    
    def addPeriode(self)->None:
        # remove the current periode and add the new periode
        with ErrorHandlerWithMessage("couldn't add the periode", self):
            updates = self.application.datas.addPeriode(self.getPeriode())
        # update the datas and kill the window
        self._updateAndKill(updates)

class RemovePeriodeDialog(PeriodeDialog):
    
    def __init__(self, master: tkinter.Misc, application: App, periode: Periode) -> None:
        super().__init__(master, application, periode)
        self.removeButton = tkinter.Button(
            self, text="remove periode", bg="maroon1", command=self.removePeriode)
        self.removeButton.grid(column=0, row=self.nbEntrys+1, sticky="we")
    
    def removePeriode(self)->None:
        # remove the current periode and add the new periode
        with ErrorHandlerWithMessage("couldn't remove the periode", self):
            updates = self.application.datas.substractPeriode(self.getPeriode())
        # update the datas and kill the window
        self._updateAndKill(updates)


class SplitPeriodeDialog(CustomTopLevel):
    def __init__(self, editPeriodeDialog: EditPeriodeDialog) -> None:
        super().__init__(editPeriodeDialog, editPeriodeDialog.application, "periode split editor")
        self.editPeriodeDialog: "EditPeriodeDialog" = editPeriodeDialog
        self.periode: Periode = self.editPeriodeDialog.periode
        
        self.splitTimeEntryLine: TextEntryLine = TextEntryLine(
            self, self.application, fixedText="when to split: ", defaultEntryText=datetimeToText(self.periode.midle))
        self.splitDurationEntryLine: TextEntryLine = TextEntryLine(
            self, self.application, fixedText="duration to remove: ", defaultEntryText="1min")
        self.splitButton = tkinter.Button(
            self, text="split periode", bg="maroon1", command=self.splitPeiode)
        
        # place each entry line
        self.grid_columnconfigure(0, weight=1)
        self.splitTimeEntryLine.grid(row=0, column=0, sticky="we")
        self.splitDurationEntryLine.grid(row=1, column=0, sticky="we")
        self.splitButton.grid(row=2, column=0, sticky="we")
    
    def splitPeiode(self)->None:
        # remove the current periode and add the new periode
        with ErrorHandlerWithMessage("couldn't split the periode", self):
            updates = self.application.datas.replacePeriodes(oldPeriode=self.periode, newPeriodes=self.getPeriodes())
        # update the datas and kill the window
        self.destroy(destroyParent=True)
        # update the datas
        self.application.updatedDatas(updates)
    
    def getPeriodes(self)->"tuple[Periode, Periode]":
        splitTime: datetime = datetimeFromText(self.splitTimeEntryLine.getEntryText())
        spacingDuration: timedelta = timedeltaFromText(self.splitDurationEntryLine.getEntryText())
        if spacingDuration == timedelta(0):
            raise ValueError("the duration to remove can't be null")
        return self.periode.split(splitTime, spacing=spacingDuration)
        
    @override
    def destroy(self, destroyParent:bool=False)->None:
        """unbind it and destroy the window"""
        self.editPeriodeDialog.splitPeriodeDialog = None
        if destroyParent is True:
            self.editPeriodeDialog.destroy()
        # kill the window
        super().destroy()

class ActivitiesTable(GenericSortableTableFrame[_ActivityColumn, Activity]):
    COLUMNS: "tuple[_ActivityColumn]" = get_args(_ActivityColumn)
    UPDATE_CONDITIONS: "set[_UpdatedTarget]" = {"activity", "periodes"}
    
    def __init__(self, activitiesManager:"ActivitiesManager") -> None:
        super().__init__(activitiesManager, activitiesManager.application)
        self.__cached_activitiesUsages: "dict[Activity, int]" = {}
        """this one must contain all the registered activities"""
        self.__cached_activitiesCumulatedTime: "dict[Activity, timedelta]" = {}
        self.updatedDatas(self.UPDATE_CONDITIONS)
        
    def getSortedElements(self)->"list[Activity]":
        sortCol, order = self.currentSortStatus
        sortFunc: "Callable[[Activity], SupportsRichComparison]"
        if sortCol == "name": sortFunc = str
        elif sortCol == "number of time used":
            sortFunc = self.__getActivityUses
        elif sortCol == "total cumulated duration":
            sortFunc = self.__getActivityTotalTime
        else: raise ValueError(f"invalide sort column: {sortCol}")
        return sorted(list(self.__cached_activitiesUsages.keys()),
                      key=sortFunc, reverse=(not order))
    
    def getElementDatas(self, element:"Activity")->"dict[_ActivityColumn, str]":
        return {"name": str(element),
                "number of time used": str(self.__getActivityUses(element)),
                "total cumulated duration": \
                    prettyTimedelta(self.__getActivityTotalTime(element))}
    
    def getElementTags(self, element:"Activity")->"tuple[str, ...]":
        return () # no tags needed for activities

    def __getActivityUses(self, activity:Activity)->int:
        return self.__cached_activitiesUsages[activity]
    def __getActivityTotalTime(self, activity:Activity)->timedelta:
        return self.__cached_activitiesCumulatedTime[activity]
    
    def updatedDatas(self, targets:"set[_UpdatedTarget]")->None:
        if targets.isdisjoint(self.UPDATE_CONDITIONS):
            return None # => none of the requirements are meeted
        self.__cached_activitiesUsages = self.application.datas.getActivitiesUsages()
        self.__cached_activitiesCumulatedTime = \
            self.application.datas.cumulatedDurationPerActivity(selectedTimeFrame='all')
        self.sortLines()
        

class ActivitiesManager(CustomTopLevel):
    
    def __init__(self, menuWidget:"MenusWidget") -> None:
        super().__init__(menuWidget, menuWidget.application, title="activities manager")
        self.menusWidget: MenusWidget = menuWidget
        
        self.activitiesTable = ActivitiesTable(self)
        self.activitiesTable.table.bind("<Double-1>", self.selectClickedActivity)
        
        self.commandsLine = WidgetsLine(self, self.application)
        btnFont = self.menusWidget.mainFrame.fonts.big
        # create a short cut for the activity selector
        self.activitySelector = ActivitySelectorLine(
            self.commandsLine, self.application, "activity to select: ", defaultActivity=None)
        # put all the widgets to the line
        self.commandsLine.addWidgets([
            self.activitySelector,
            tkinter.Button(self.commandsLine, text="register a new activity", 
                           command=self.registerNewActivity, font=btnFont, bg="green2"),
            tkinter.Button(self.commandsLine, text="remove the selected activity",
                           command=self.removeSelectedActivity, font=btnFont, bg="darkorange1")])
        
        
        # makes the tabl take the maximum space available
        self.commandsLine.placeButtons(packing="grid")
        self.activitiesTable.pack(anchor="n", fill="both", side=tkinter.TOP)
        self.commandsLine.pack(anchor="sw", fill="x", side=tkinter.BOTTOM)
    
    def selectClickedActivity(self, event:"tkinter.Event")->None:
        # ge the seleected item
        selection: "tuple[str, ...]" = self.activitiesTable.table.selection()
        if len(selection) != 1: 
            return None # => not a single item selected
        # get the name of the selected activity
        nameColumn = self.activitiesTable.COLUMNS.index("name")
        activityName = assertIsinstance(
            str, self.activitiesTable.table.item(selection[0])["values"][nameColumn])
        # set the activity name in the selector
        self.activitySelector.var.set(activityName)
        
    
    def getSelectedActivity(self)->"Activity":
        return Activity(self.activitySelector.getEntryText())
    
    def registerNewActivity(self)->None:
        newActivity: Activity = self.getSelectedActivity()
        updates: "set[_UpdatedTarget]" = self.application.datas.registerActivity(newActivity)
        self.application.updatedDatas(updates)
        if len(updates) == 0:
            # => no updates
            tkinter.messagebox.showinfo(
                title="new activity", message=f"the activity: {newActivity} is alredy registered")
            self.focus()
    
    def removeSelectedActivity(self)->None:
        selectedActivity: Activity = self.getSelectedActivity()
        with ErrorHandlerWithMessage("can't remove this activity", self):
            updates = self.application.datas.unregisterActivity(selectedActivity)
        self.application.updatedDatas(updates)
        
    
    def updatedDatas(self, targets:"set[_UpdatedTarget]")->None:
        self.activitiesTable.updatedDatas(targets)
        
    @override
    def destroy(self)->None:
        """unbind it and destroy the window"""
        self.menusWidget.activitiesManager = None
        super().destroy()


class ActivitiesCheckableFrame(tkinter.Frame):
    UPDATE_CONDITIONS: "set[_UpdatedTarget]" = {"activity", }
    
    def __init__(self, master:tkinter.Misc, application:App)->None:
        super().__init__(master=master, bg=master["background"])
        self.application: App = application
        
        self.textLabel = tkinter.Label(
            self, text="select the activities: ", bg=self["background"])
        self.buttonsFrame = tkinter.Frame(self, bg=self["background"])
        self.textLabel.pack(fill="x", anchor="center", side="top")
        self.buttonsFrame.pack(fill="both", anchor="center", side="top")
        
        self.activitiesCheckBoxes: "dict[Activity, tkinter.Checkbutton]" = {}
        self.activitiesValues: "dict[Activity, tkinter.BooleanVar]" = {}
        self.updatedDatas(self.UPDATE_CONDITIONS)
    
    def getSelectedActivities(self)->"set[Activity]":
        return {activity for activity, var in self.activitiesValues.items()
                if var.get() is True}
    
    def __generateActivitiesCheckBoxes(self, activities:"list[Activity]")->None:
        """generate the buttons of the activities (keep their state)"""
        NB_ROWS: int = int(len(activities) ** 0.5)
        selectedActivies: "set[Activity]" = self.getSelectedActivities()
        currentActivities: "set[Activity]" = set(self.activitiesValues.keys())
        activitiesToRemove: "set[Activity]" = currentActivities.difference(activities)
        """all activity in `currentActivities` but not in `activities`"""
        # clear the current activities items
        for activity in activitiesToRemove:
            button = self.activitiesCheckBoxes.pop(activity)
            self.activitiesValues.pop(activity)
            button.destroy()
            del activity, button
        # add the new activities
        for index, activity in enumerate(activities):
            # create the tkinter elements
            if activity not in self.activitiesValues:
                var = tkinter.BooleanVar(value=(activity in selectedActivies))
                button = tkinter.Checkbutton(
                    self.buttonsFrame, text=str(activity), 
                    bg=self.buttonsFrame["background"],
                    variable=var, onvalue=True, offvalue=False)
                # bind them to the structure
                self.activitiesValues[activity] = var
                self.activitiesCheckBoxes[activity] = button
                del button, var
            # place the button
            column, row = divmod(index, NB_ROWS)
            self.activitiesCheckBoxes[activity].grid(
                row=row, column=column, sticky="nw")
            del activity, row, column
            

    def updatedDatas(self, targets:"set[_UpdatedTarget]")->None:
        if self.UPDATE_CONDITIONS.isdisjoint(targets):
            return None # => condition not meets
        registeredActivities: "list[Activity]" = \
            self.application.datas.getRegisteredActivites()
        self.__generateActivitiesCheckBoxes(registeredActivities)

class ExportDialog(CustomTopLevel):
    def __init__(self, menusWidget:MenusWidget) -> None:
        super().__init__(menusWidget, menusWidget.application, "export window")
        self.menusWidget: "MenusWidget" = menusWidget

        currentSelectedInterval: "_TimeID" = self.application.datas.get_TimeID(None, None).asTimeID()
        # create the widgets
        self.checkActivitiesFrame = ActivitiesCheckableFrame(self, self.application)
        self.intervalStartEntry = TextEntryLine(
            self, self.application, "start of the export interval (or 'all'): ", 
            defaultEntryText=datetimeToText(currentSelectedInterval.startTime))
        self.intervalEndEntry = TextEntryLine(
            self, self.application, "end of the export interval (or 'all'): ", 
            defaultEntryText=datetimeToText(currentSelectedInterval.endTime))
        del currentSelectedInterval
        self.exportButton = tkinter.Button(
            self, text="export to file", command=self.export, bg="maroon1")
        
        # place the widgets
        self.checkActivitiesFrame.grid(column=0, row=0)
        self.intervalStartEntry.grid(column=0, row=1)
        self.intervalEndEntry.grid(column=0, row=2)
        self.exportButton.grid(column=0, row=3)
    
    def export(self)->None:
        filePath: "Path|None" = self.application.askFilenameToSaveDatas(master=self)
        if filePath is None: # => no file selected
            tkinter.messagebox.showerror(
                title="operation canceled", 
                message="no file selected, can't export the datas")
            return None
        exportDatas = self.application.datas.exportPeriodes(
            selectedInterval=self.getSelectedTimeInterval(), 
            selectedActivities=self.checkActivitiesFrame.getSelectedActivities(), 
            useConfig="export")
        self.application.safeSaveToFile(datas=exportDatas, filePath=filePath)
    
    def getSelectedTimeInterval(self)->"_TimeID":
        return getSelectedTimeInterval(
            startIntervalText=self.intervalStartEntry.getEntryText().strip(),
            endIntervalText=self.intervalEndEntry.getEntryText().strip(),
            datas=self.application.datas)

    def updatedDatas(self, targets:"set[_UpdatedTarget]")->None:
        self.checkActivitiesFrame.updatedDatas(targets)

    @override
    def destroy(self) -> None:
        self.menusWidget.exportDialog = None
        super().destroy()



class ScheduleDialog(CustomTopLevel):
    def __init__(self, menusWidget:MenusWidget) -> None:
        super().__init__(menusWidget, menusWidget.application, "schedule generator window")
        self.menusWidget: "MenusWidget" = menusWidget

        currentSelectedInterval: "_TimeID" = self.application.datas.get_TimeID(None, None).asTimeID()
        # create the widgets
        self.expainationText = tkinter.Label(
            self, padx=5, pady=15, bg=self["background"], justify="left",
            text=("genrate an svg schedule of all the periodes inside the selected interval\n"
                  + "unfortunately no perview can be generated\n"
                  + "the different types of schedules are:\n"
                  + " - interval duration <= 7 day: line schedule\n"
                  + " - sub periode of a month: 1 line per week\n"
                  + " - across multiple months: 1 line per month\n\n"
                  + "tips: you can export the datas to create a copy\n"
                  + "  in order to select precisely the periodes you whant"))
        self.intervalStartEntry = TextEntryLine(
            self, self.application, "start of the schedule interval (or 'all'): ", 
            defaultEntryText=datetimeToText(currentSelectedInterval.startTime))
        self.intervalEndEntry = TextEntryLine(
            self, self.application, "end of the schedule interval (or 'all'): ", 
            defaultEntryText=datetimeToText(currentSelectedInterval.endTime))
        del currentSelectedInterval
        self.generateButton = tkinter.Button(
            self, text="generate to file", command=self.generate, bg="maroon1")
        
        # place the widgets
        self.grid_columnconfigure(0, weight=1)
        self.expainationText.grid(column=0, row=0)
        self.intervalStartEntry.grid(column=0, row=1, sticky="we")
        self.intervalEndEntry.grid(column=0, row=2, sticky="we")
        self.generateButton.grid(column=0, row=3, sticky="we")
    
    def generate(self)->None:
        # ask a file to save
        saveFilePath: "Path|None" = self.application.askFilenameToSaveGeneric(
            master=self, title="file to save the schedule",
            directory=SCHEDULES_DIRECTORY, fileExtentions=SCHEDULE_FILE_TYPES)
        if saveFilePath is None: # => no file selected, don't save anything
            tkinter.messagebox.showerror(
                title="operation canceled",
                message="no file selected, can't generate the schedule")
            return None
        # get the interval, the periodes and generate the schedule
        selectedInterval: "_TimeID" = self.getSelectedTimeInterval()
        periodes = self.application.datas.getPeriodes(selectedInterval.startTime, selectedInterval)
        with ErrorHandlerWithMessage("couldn't draw the schedule", self):
            svgDrawing = drawSchedule(periodes)
            # set the lasts parameters
            svgDrawing.set_pixel_scale(1080)
            svgDrawing.append_title(self.application.datas.getConfigText("name"))
        
        # save to the file
        with open(saveFilePath, mode="w") as saveFile:
            if saveFilePath.suffix == ".html":
                svgDrawing.as_html(output_file=saveFile)
            else: # => expect an svg (or other)
                svgDrawing.as_svg(output_file=saveFile)
        tkinter.messagebox.showinfo(
            title="sucessfull operation", message="the schedule is generated and saved")
        
    
    def getSelectedTimeInterval(self)->"_TimeID":
        return getSelectedTimeInterval(
            startIntervalText=self.intervalStartEntry.getEntryText().strip(),
            endIntervalText=self.intervalEndEntry.getEntryText().strip(),
            datas=self.application.datas)

    @override
    def destroy(self) -> None:
        self.menusWidget.scheduleDialog = None
        super().destroy()





class ErrorHandlerWithMessage(SupportsContext):
    def __init__(self, title:str, master:tkinter.Misc) -> None:
        self.master:tkinter.Misc = master
        self.title: str = title
    
    def __enter__(self)->None:
        pass
    def __exit__(self, exc_type:"type[Exception]|None", exc_value:"Exception|None", traceback:"TracebackType|None")->"None|bool":
        if exc_value is None: 
            # => no error !
            return None
        exceptionText: str = '\n'.join(exc_value.args)
        tkinter.messagebox.showerror(
            title=self.title, 
            message=f"\t{self.title}\n\nthe following error happend:\n\t{exceptionText}"
        )
        self.master.focus()
        return False
    

class FontsManger():
    def __init__(self, master:"tkinter.Misc", normal:"None|Font",
                 small:"None|Font"=None, big:"None|Font"=None) -> None:
        self.normal: Font = normal or Font(root=master)
        self.small: Font = small or self.resize(self.normal, 0.75)
        self.big: Font = big or self.resize(self.normal, 1.25)
        self.smaller: Font = self.resize(self.small, 0.75)
        self.biger: Font = self.resize(self.big, 1.25)
    
    @staticmethod
    def resize(font: Font, newSize:"float")->Font:
        newFont: Font = font.copy()
        newFont.configure(size=int(newSize*font.cget("size")))
        return newFont

class Args(TypedDict):
        openDatasPath: "str|None"

def main(progFile:str)->None:
    # logger works automaticaly, nothing to do :)
    logger: Logger = Logger(
        LOGGS_FILE_PATH, fileOpenMode="w",
        newLogLineAfter=timedelta(milliseconds=50))
    
    if os.name == "nt":
        # => on windows
        # it allow windows to use the correct icon
        ctypes.windll.shell32.\
            SetCurrentProcessExplicitAppUserModelID("holo.workTime.application")
    
    argumentParser = argparse.ArgumentParser(prog=progFile)
    argumentParser.add_argument("--open", action="store", dest="openDatasPath", default=None,
                                required=False, help="the file to open when starting the app")
    args = Args(**argumentParser.parse_args().__dict__)
    
    app = App(args)
    app.run()


if __name__ == "__main__":
    main(__file__)