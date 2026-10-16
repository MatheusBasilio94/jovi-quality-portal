"""Consistent action statistics charts, built only when Statistics is open."""
from collections import Counter
from datetime import datetime
from math import ceil, floor, log10
from zoneinfo import ZoneInfo

import pandas as pd
import plotly.graph_objects as go

from tools.defect_actions import AREAS, STATUSES

BLUE = '#2563EB'
PURPLE = '#7752D9'
GREEN = '#07854B'
NAVY = '#0B1F3A'
STATUS_COLORS = [BLUE, PURPLE, '#B77909', GREEN]
AREA_COLORS = {'SMT': BLUE, 'Assembly': PURPLE, 'IQC': '#087F8C', 'Lab': '#9462CB', 'Other': '#64748B'}
CHART_CONFIG = dict(displayModeBar=True, displaylogo=False, responsive=True,
    modeBarButtonsToRemove=['zoom2d','pan2d','select2d','lasso2d','zoomIn2d','zoomOut2d','autoScale2d','resetScale2d','toggleSpikelines'],
    toImageButtonOptions=dict(format='png', width=916, height=463, scale=3))


def _layout(figure, title, labels, maximum, *, height=360, x_title=''):
    raw = max(float(maximum)/5, 1)
    scale = 10**floor(log10(raw))
    step = next(int(multiplier*scale) for multiplier in [1,2,5,10] if multiplier*scale >= raw)
    top = max(step, ceil(maximum*1.18/step)*step)
    figure.update_layout(template='plotly_white', height=height,
        title=dict(text=title, x=0.04, font=dict(size=18, color=NAVY)),
        font=dict(family='Arial', size=13, color=NAVY),
        paper_bgcolor='#FFFFFF', plot_bgcolor='#F8FAFD',
        margin=dict(l=55,r=25,t=65,b=70), bargap=0.4,
        hoverlabel=dict(bgcolor='#FFFFFF',font_color=NAVY),
        meta={'jovi_report_export':'breakdown'})
    count = len(labels)
    tick_indices = list(range(0, count, max(1,ceil(count/18))))
    if count and count-1 not in tick_indices: tick_indices.append(count-1)
    figure.update_xaxes(title_text=x_title, tickmode='array', tickvals=tick_indices,
        ticktext=[labels[i] for i in tick_indices], tickangle=-35 if count>12 else 0,
        range=[-0.65,max(count-1,0)+0.65], showgrid=False, zeroline=False,
        showline=True,linecolor='#C8D3E3',automargin=True,fixedrange=True)
    figure.update_yaxes(title_text='Actions', tickmode='linear', tick0=0,dtick=step,tickformat=',.0f',
        range=[0,top], gridcolor='#DDE5F0',zeroline=False,automargin=True,fixedrange=True)
    return figure


def count_chart(records, dimension):
    counts = Counter(record[dimension] for record in records)
    if dimension=='status':
        categories, colors, title = STATUSES, STATUS_COLORS, 'Actions by status'
    elif dimension=='area':
        categories = [area for area in AREAS if counts[area]]
        colors, title = [AREA_COLORS[area] for area in categories], 'Actions by area'
    else:
        raise ValueError('Select status or area for action counts.')
    values = [counts[category] for category in categories]
    figure = go.Figure(go.Bar(x=list(range(len(categories))),y=values,width=0.42,
        marker_color=colors,text=values,textposition='outside',cliponaxis=False,
        textfont=dict(size=14,color=NAVY),customdata=categories,
        hovertemplate='%{customdata}<br>Actions: %{y:,.0f}<extra></extra>'))
    figure.update_layout(showlegend=False)
    labels = [category.replace('Pending verification','Pending<br>verification') for category in categories]
    return _layout(figure,title,labels,max(values,default=0))


def _local_day(value):
    timestamp = datetime.fromisoformat(value)
    if timestamp.tzinfo is None: timestamp = timestamp.replace(tzinfo=ZoneInfo('America/Manaus'))
    return timestamp.astimezone(ZoneInfo('America/Manaus')).date()


def action_timeline(records):
    created, closed = Counter(), Counter()
    for record in records:
        created[_local_day(record['created_at'])] += 1
        if record['status']=='Closed' and record.get('closed_at'):
            closed[_local_day(record['closed_at'])] += 1
    if not created:
        return pd.DataFrame(columns=['Period','Created','Closed']), 'Daily'
    days = pd.date_range(min([*created,*closed]),max([*created,*closed]))
    frame = pd.DataFrame({'Created':[created[day.date()] for day in days],
                          'Closed':[closed[day.date()] for day in days]},index=days)
    grain = 'Daily'
    if len(days)>180:
        frame = frame.resample('MS').sum()
        grain = 'Monthly'
    elif len(days)>31:
        frame = frame.resample('W-MON',label='left',closed='left').sum()
        # Do not label the first bucket with a date outside the actual scope.
        frame.index = pd.DatetimeIndex([max(day,days[0]) for day in frame.index])
        grain = 'Weekly'
    frame.insert(0,'Period',frame.index.strftime('%m/%y' if grain=='Monthly' else '%d/%m/%y'))
    return frame.reset_index(drop=True), grain


def timeline_chart(records):
    frame, grain = action_timeline(records)
    figure = go.Figure()
    for name,color in [('Created',BLUE),('Closed',GREEN)]:
        values = frame[name].tolist()
        figure.add_trace(go.Bar(name=name,x=list(range(len(frame))),y=values,width=0.28,
            offsetgroup=name,marker_color=color,text=[str(value) if value else '' for value in values],
            textposition='outside',cliponaxis=False,textfont=dict(size=13,color=NAVY),
            customdata=frame['Period'].tolist(),
            hovertemplate=f'%{{customdata}}<br>{name}: %{{y:,.0f}}<extra></extra>'))
    maximum = max([*frame['Created'],*frame['Closed']],default=0)
    _layout(figure,f'Actions created and closed · {grain}',frame['Period'].tolist(),maximum,
            height=400,x_title={'Daily':'Date','Weekly':'Week starting','Monthly':'Month'}[grain])
    figure.update_layout(barmode='group',showlegend=True,height=460,
        margin=dict(l=55,r=25,t=65,b=150),
        legend=dict(orientation='h',x=0.5,xanchor='center',y=-0.36,yanchor='top',title_text=''))
    return figure
