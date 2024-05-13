import drawsvg
from math import floor, ceil
from datetime import datetime, timedelta, time

from holo.__typing import (
    NamedTuple, Callable, Any, 
)

from model import (
    FullDatas, PeriodesStorage, _TimeID, Periode, _DayID, _MonthID,
    prettyTimedelta, prettyDatetime,
)

class GridPos(NamedTuple):
    row: int
    col: int

class GridInfos(NamedTuple):
    nbCols: int 
    nbRows: int
    daysToGrid: "dict[_DayID, GridPos]"
    days: "list[_DayID]"

class DrawingConstants(NamedTuple):
    STROKE: float
    STROKE_MEDIUM: float
    STROKE_SMALL: float
    FONT_SIZE: float
    FONT_SIZE_SMALL: float
    DASHES_ARRAY: "tuple[float, ...]"
    

class DrawingInfos(NamedTuple):
    draw: "drawsvg.Drawing"
    gridInfos: "GridInfos"
    getDayRect: "Callable[[GridPos], DrawingRect]"
    consts: "DrawingConstants"
    

class DrawingRect(NamedTuple):
    x: float
    y: float
    width: float
    height: float
    


def __computeGridSizeAndDaysToGrid(timeFrame:"_TimeID")->GridInfos:
    days: "dict[_DayID, _TimeID]" = \
        {_DayID.fromDatetime(interval.startTime): _TimeID.fromDuration(p.startTime, p.duration)
         for interval, p in timeFrame.splitPer_TimeFrame("day").items()}
    months: "dict[_MonthID, _TimeID]" = \
        {_MonthID.fromDatetime(interval.startTime): _TimeID.fromDuration(p.startTime, p.duration)
         for interval, p in timeFrame.splitPer_TimeFrame("month").items()}
    sortedDays = sorted(days.keys(), key=lambda day:day.startTime)
    NB_DAYS = len(days)
    NB_MONTHS =  len(months)
    print(f"acrros: {NB_DAYS} days and {NB_MONTHS} months, of duration: {prettyTimedelta(timeFrame.duration, useDays=True)}")

    # determine visual mode and the number of cols/rows

    dayToGrid: "dict[_DayID, GridPos]"
    assert NB_MONTHS != 0
    if NB_MONTHS == 1:
        # week or months mode
        NB_COLS = (NB_DAYS if timeFrame.duration <= timedelta(days=7) else 7)
        NB_ROWS = ceil(NB_DAYS / NB_COLS)
        dayToGrid = {day: GridPos(*divmod(index, NB_COLS))
                     for index, day in enumerate(sortedDays)}
    else: # => many months
        NB_ROWS = NB_MONTHS
        NB_COLS = 0
        dayToGrid = {}
        for indexMonth, interval in enumerate(months.values()):
            daysOfMonth = sorted(interval.splitPer_TimeFrame("day").keys(),
                                key=lambda day:day.startTime)
            NB_COLS = max(NB_COLS, len(daysOfMonth))
            for indexDay, day in enumerate(daysOfMonth):
                day = _DayID.fromDatetime(day.startTime)
                dayToGrid[day] = GridPos(row=indexMonth, col=indexDay)
                del day, indexDay
            del interval, indexMonth, daysOfMonth
    
    return GridInfos(nbCols=NB_COLS, nbRows=NB_ROWS, daysToGrid=dayToGrid, days=sortedDays)


def drawEmptySchedule(timeFrame:"_TimeID")->"DrawingInfos":
    # 3 cas
    # - 1 ligne (timeFrame <= 7 days):
    #       - on a besoin de jusqu'a 8 jours
    # - 2->5 lignes (7 < timeFrame <= 31 days):
    #       - 7 jours par ligne
    # - 2->inf lignes (31 days < timeFrame)
    #       - jusqu'a 31 jours par ligne
    # on grise les parties des jours qui ne sont pas dans la timeFrame
    
    gridInfos = __computeGridSizeAndDaysToGrid(timeFrame)
    
    def getDayRect(gridPos:"GridPos")->"DrawingRect":
        xRect = MARGIN_LEFT + WIDTH_TEXT_LEFT_ZONE + gridPos.col*widthRectDay
        yRect = MARGIN_TOP + gridPos.row*(heightRectDay + HEIGHT_TEXT_UNDER_ZONE)
        return DrawingRect(x=xRect, y=yRect, width=widthRectDay, height=heightRectDay)
        

    NB_SUB_RECTS = 24 # one per hours
    W, H = (gridInfos.nbCols/7, gridInfos.nbRows*9/16)
    W_RATIO = W / gridInfos.nbCols * 7
    H_RATIO = H / gridInfos.nbRows * 2

    draw = drawsvg.Drawing(width=W, height=H)

    CONSTANTS = DrawingConstants(
        STROKE = 0.00_15 * H_RATIO,
        STROKE_MEDIUM = 0.00_08 * H_RATIO,
        STROKE_SMALL = 0.00_05 * H_RATIO,
        FONT_SIZE = 18/1080 * W_RATIO,
        FONT_SIZE_SMALL = 10/1080 * W_RATIO,
        DASHES_ARRAY=(0.00_1 * W_RATIO, 0.00_2 * W_RATIO))
    HEIGHT_TEXT_UNDER_ZONE = 0.03 * H_RATIO
    WIDTH_TEXT_LEFT_ZONE = 0.02 * H_RATIO
    

    MARGIN_TOP = 0.01 * W_RATIO
    MARGIN_BOTTOM = 0.00 * W_RATIO
    MARGIN_LEFT = 0.01 * W_RATIO
    MARGIN_RIGHT = 0.01 * W_RATIO

    widthRectDay = (W-MARGIN_LEFT-MARGIN_RIGHT-WIDTH_TEXT_LEFT_ZONE) / gridInfos.nbCols
    heightRectDay = ((H-MARGIN_TOP-MARGIN_BOTTOM)) / gridInfos.nbRows - HEIGHT_TEXT_UNDER_ZONE
    dyLine = heightRectDay / NB_SUB_RECTS
    for day, gridPos in gridInfos.daysToGrid.items():
        rectDay = getDayRect(gridPos)

        draw.append(drawsvg.Rectangle(
            x=rectDay.x, y=rectDay.y, width=widthRectDay, height=heightRectDay,
            fill="none", stroke="black", stroke_width=CONSTANTS.STROKE))
        
        dayTextKwargs: "dict[str, Any]" = {}
        if day.startTime.isocalendar()[2] == 1: # monday
            dayTextKwargs = {"font_weight": "bold", "text_decoration": "underline"}
        draw.append(drawsvg.Text(
            text=prettyDatetime(day.startTime, 'date'),
            font_size=CONSTANTS.FONT_SIZE, dominant_baseline="hanging",
            x=rectDay.x, y=rectDay.y+heightRectDay, **dayTextKwargs))
        
        for hour in range(0, NB_SUB_RECTS):
            yLine = rectDay.y + hour*dyLine
            draw.append(drawsvg.Text(
                f"{hour:02d}h", font_size=CONSTANTS.FONT_SIZE_SMALL,
                x=MARGIN_LEFT, y=yLine, dominant_baseline="hanging"))
            hourLineKwargs: "dict[str, Any]"
            if hour % 4 == 0:
                hourLineKwargs = {"stroke_width": CONSTANTS.STROKE_MEDIUM}
            else: hourLineKwargs = {"stroke_width": CONSTANTS.STROKE_SMALL,
                                    "stroke_dasharray": ','.join(map(str, CONSTANTS.DASHES_ARRAY))}
            draw.append(drawsvg.Line(
                sx=rectDay.x, ex=rectDay.x+widthRectDay, 
                sy=yLine, ey=yLine, stroke="black",
                **hourLineKwargs))
            del hour, yLine
        del day, gridPos, rectDay

    # remove the part of the first day that isn't in the timeFrame
    if timeFrame.startTime.time() != time(0, 0):
        rectDay = getDayRect(gridInfos.daysToGrid[gridInfos.days[0]]) # pos of first day
        t = timeFrame.startTime.time()
        hRem = heightRectDay * (t.hour*3600 + t.minute*60 + t.second) / (24 * 3600)
        draw.append(drawsvg.Rectangle(
            x=rectDay.x, y=rectDay.y,
            width=widthRectDay, height=hRem,
            fill="gray", fill_opacity=0.7))
    # remove the part of the last day that isn't in the timeFrame
    if timeFrame.endTime.time() != time.min: # => not 00h00 => some time to remove
        rectDay = getDayRect(gridInfos.daysToGrid[gridInfos.days[-1]]) # pos of last day
        t = timeFrame.endTime.time()
        hRem = heightRectDay * (t.hour*3600 + t.minute*60 + t.second) / (24 * 3600)
        draw.append(drawsvg.Rectangle(
            x=rectDay.x, y=rectDay.y+hRem, 
            width=widthRectDay, height=heightRectDay-hRem, 
            fill="gray", fill_opacity=0.7))

    return DrawingInfos(draw=draw, gridInfos=gridInfos, getDayRect=getDayRect, consts=CONSTANTS)
    
    
    

def drawSchedule(periodes:"PeriodesStorage[_TimeID]")->"drawsvg.Drawing":
    # check it is the correct duration
    drawingInfos = drawEmptySchedule(periodes.timeframe)
    
    def getSubDrawRect(day:"_DayID", periode:"Periode")->"DrawingRect":
        assert timedelta(0) < periode.duration <= timedelta(days=1)
        drawRect = drawingInfos.getDayRect(drawingInfos.gridInfos.daysToGrid[day])
        if periode.duration == timedelta(days=1):
            return drawRect
        # => less than a day
        # crop the start
        startT = periode.startTime.time()
        timeToRemove: float = startT.hour*3600 + startT.minute*60 + startT.second + startT.microsecond*1e-6
        y: float = drawRect.y + drawRect.height * (timeToRemove / (24 * 3600))
        # crop the end
        rectEndY = drawRect.y + drawRect.height
        endT = periode.endTime.time()
        if endT != time.min: # => not 00h00
            height: float = drawRect.height * (periode.duration / timedelta(days=1))
        else: height = rectEndY - y
        # create the rect
        return DrawingRect(x=drawRect.x, y=y, width=drawRect.width, height=height)
    
    for periode in periodes:
        # get the sub periodes per days
        for day, subPeriode in periode.splitPer_TimeFrame("day").items():
            # conver to a valide key and skip if needed
            if subPeriode.duration == timedelta(0):
                print(f"empty subPeriode ?! -> {repr(subPeriode)}")
                continue # nothing to render
            day = _DayID.fromDatetime(day.startTime)
            
            # compute and draw the rect of the sub periode
            drawRect = getSubDrawRect(day=day, periode=subPeriode)
            drawingInfos.draw.append(drawsvg.Rectangle(
                x=drawRect.x, y=drawRect.y, width=drawRect.width, height=drawRect.height,
                fill="red", fill_opacity=0.5))
            
            # compute the text of the sub periode
            subPeriodeTexts: "list[str]" = []
            if subPeriode.activity != None:
                subPeriodeTexts.append("activity: ")
                subPeriodeTexts.append(str(subPeriode.activity))
            if (subPeriode.duration > timedelta(minutes=40)) or (len(subPeriodeTexts) == 0):
                subPeriodeTexts.append("\n")
                subPeriodeTexts.append(prettyDatetime(subPeriode.startTime, 'time'))
                subPeriodeTexts.append(" -> ")
                subPeriodeTexts.append(prettyDatetime(subPeriode.endTime, 'time'))
            # else: => if it show the activity there is not enought place for the interval ()
            
            # draw the text of the sub periode
            drawingInfos.draw.append(drawsvg.Text(
                text="".join(subPeriodeTexts),
                x=drawRect.x, y=drawRect.y,
                font_size=drawingInfos.consts.FONT_SIZE_SMALL, 
                dominant_baseline="hanging",))
                    
    return drawingInfos.draw


"""
from holo import prettyPrint
timeFrame = _TimeID.fromText("22/04/2024-07h00:00", "13/05/2024-07h00:00")
#timeFrame = _WeekID.fromDatetime(datetimeFromText("12/05/2025-23h01:56"))

with open("datas/codding copy.json", mode="rb") as file:
    datas = FullDatas.fromFile(file)

periodes = datas.getPeriodes(timeFrame.startTime, timeFrame)
draw = drawSchedule(periodes)
draw.set_pixel_scale(1080)
"""
