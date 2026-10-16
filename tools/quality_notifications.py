"""Deterministic quality signals. No forecasts, inferred inputs or simulated exclusions."""
from datetime import timedelta
from hashlib import sha256
import json

import pandas as pd

MIN_INPUT = 100
RECURRENCE_PCBS = 3


def _notice(kind, area, model, title, message, day, marker, tab='KPI Track'):
    identity = json.dumps([kind, area, model, marker], sort_keys=True, default=str)
    return {'id': sha256(identity.encode()).hexdigest(), 'kind': kind, 'area': area,
            'model': model, 'title': title, 'message': message,
            'date': f'{day.isoformat()}T23:59:59-04:00', 'destination': area, 'tab': tab}


def _label(value, direction):
    return f'{value:,.0f} PPM' if direction == 'max' else f'{value:.2%}'


def collect_kpi_signals(points, directory, through):
    """Use the latest eligible observation and three eligible days (two strict changes)."""
    notices = []
    definitions = {item['source']: item for item in directory}
    frame = pd.DataFrame(points)
    if frame.empty:
        return notices
    frame['day'] = pd.to_datetime(frame['day']).dt.date
    frame['value'] = pd.to_numeric(frame['value'], errors='coerce')
    # An unavailable/invalid observation cannot become a zero-defect day.
    frame = frame[frame['day'].le(through) & frame['input'].ge(MIN_INPUT) & frame['value'].notna()]
    for (source, model), group in frame.groupby(['source', 'model'], sort=True):
        item = definitions[source]
        group = group.sort_values('day').drop_duplicates('day', keep='last')
        latest = group.iloc[-1]
        if latest['day'] < through - timedelta(days=6):
            continue
        value, target = float(latest['value']), float(item['target'])
        context = f"{item['area']} · {model} · {item['kpi']}"
        worse = value > target if item['direction'] == 'max' else value < target
        if worse:
            notices.append(_notice('target', item['area'], model, 'KPI outside target',
                f"{context}: {_label(value, item['direction'])} on {latest['day']:%d/%m}. "
                f"Target {'≤' if item['direction']=='max' else '≥'} {_label(target, item['direction'])}; "
                f"input {int(latest['input']):,} PCBs.", latest['day'],
                [source, latest['day'], value, target]))
        last = group.tail(3)
        if len(last) == 3:
            changes = last['value'].diff().iloc[1:]
            deteriorating = changes.gt(1e-12).all() if item['direction'] == 'max' else changes.lt(-1e-12).all()
            if deteriorating:
                sequence = ' → '.join(f"{r.day:%d/%m}: {_label(r.value, item['direction'])}" for r in last.itertuples())
                notices.append(_notice('trend', item['area'], model, 'KPI worsening over 3 production days',
                    f'{context}: {sequence}. Each day has at least {MIN_INPUT} input PCBs.',
                    latest['day'], [source, list(zip(last['day'], last['value'])), target]))
    return notices


def collect_recurrences(records, area, through):
    """Distinct model + SN counts in seven calendar days; duplicates never inflate counts."""
    if records.empty:
        return []
    frame = records.copy()
    frame['day'] = pd.to_datetime(frame['day'], errors='coerce').dt.date
    frame = frame[frame['day'].between(through - timedelta(days=6), through)]
    for column in ['model', 'pcb', 'defect', 'component']:
        frame[column] = frame[column].fillna('').astype(str).str.strip()
    frame = frame[frame['pcb'].ne('') & frame['defect'].ne('') & frame['model'].ne('')]
    frame['board'] = frame['model'].str.casefold() + '|' + frame['pcb'].str.casefold()
    frame['defect_key'] = frame['defect'].str.casefold()
    frame['component_key'] = frame['component'].str.casefold()
    notices = []
    for model in ['All models', *sorted(frame['model'].unique())]:
        selected = frame if model == 'All models' else frame[frame['model'].eq(model)]
        for component_scope in [False, True]:
            scoped = selected[selected['component'].ne('')] if component_scope else selected
            keys = ['defect_key', 'component_key'] if component_scope else ['defect_key']
            for _, group in scoped.groupby(keys, sort=True):
                count = int(group['board'].nunique())
                if count < RECURRENCE_PCBS:
                    continue
                defect = group.iloc[0]['defect']
                component = group.iloc[0]['component'] if component_scope else ''
                start, end = group['day'].min(), group['day'].max()
                notices.append(_notice('component' if component_scope else 'recurrence', area, model,
                    'Repeated defect on the same component' if component_scope else 'Recurring defect',
                    f'{area} · {model}: {defect}' + (f' · {component}' if component else '') +
                    f' — {count} distinct PCBs, {start:%d/%m}–{end:%d/%m} (last 7 calendar days). '
                    'Review the cause; recurrence alone does not confirm an epidemic.',
                    end, [defect.casefold(), component.casefold(), sorted(set(group['board'])), start, end],
                    'Quality Dashboard'))
    return notices


def prepared_recurrences(frame, area):
    """Preserve recorded phenomenon and component identity rather than guessing a cause."""
    if frame.empty:
        return pd.DataFrame()
    result = pd.DataFrame(index=frame.index)
    result['day'] = frame['KPIDate' if area == 'SMT' else 'DefectDate']
    result['pcb'] = frame['PCB' if area == 'SMT' else 'PCBNormalized']
    result['model'] = frame['Model']
    result['defect'] = frame['Phenomenon']
    item = frame.get('ItemCode', pd.Series('', index=frame.index)).fillna('').astype(str).str.strip()
    location = frame.get('Location' if area == 'SMT' else 'BadMachLocation', pd.Series('', index=frame.index)).fillna('').astype(str).str.strip()
    # A component code matches across locations; a location is the fallback when no code exists.
    result['component'] = item.map(lambda value: 'ItemCode: '+value if value else '').where(item.ne(''),
        location.map(lambda value: 'Location: '+value if value else ''))
    result.loc[result['component'].str.casefold().isin(['itemcode: unknown', 'location: unknown']), 'component'] = ''
    return result


def build_points(smt, assembly, inspections, through):
    """Daily input-backed metrics, using the existing validated calculations and scopes."""
    from tools import assembly_kpi_v2
    points, recurrence = [], []

    def add(frame, model, mapping, date_column, input_column, low, high):
        if frame.empty or low is None or high is None or pd.isna(low) or pd.isna(high):
            return
        low, high = pd.Timestamp(low).date(), pd.Timestamp(high).date()
        for _, row in frame.iterrows():
            day = pd.Timestamp(row[date_column]).date()
            if not low <= day <= min(high, through):
                continue
            for source, value_column in mapping.items():
                points.append({'source': source, 'model': model, 'day': day,
                               'input': float(row[input_column]), 'value': row[value_column]})

    inputs_by_area = {}
    if smt is not None:
        inputs = smt['selected_input'].copy()
        confirmed = smt['covered_raw'][~smt['covered_raw']['IsRejudgeOK'].fillna(False).astype(bool)].copy()
        confirmed = confirmed[confirmed['FailureType'].isin(['Functional Failure', 'Appearance Failure'])]
        recurrence.extend(collect_recurrences(prepared_recurrences(confirmed, 'SMT'), 'SMT', through))
        exact = inputs[inputs['Granularity'].eq('daily')].copy()
        exact['Date'] = exact['BeginDate']
        coarse = inputs[~inputs['Granularity'].eq('daily')]
        usable = []
        for model in ['All models', *sorted(exact['Model'].unique())]:
            selected = exact if model == 'All models' else exact[exact['Model'].eq(model)]
            uncertain = coarse if model == 'All models' else coarse[coarse['Model'].eq(model)]
            defects = confirmed if model == 'All models' else confirmed[confirmed['Model'].eq(model)]
            rows = []
            for day, day_input in selected.groupby('Date'):
                # Never treat prorated weekly/monthly input as an observed daily sample.
                if ((uncertain['BeginDate'] <= day) & (uncertain['EndDateExclusive'] > day)).any():
                    continue
                n = float(day_input['Input'].sum())
                bad = defects[defects['KPIDate'].eq(day)]
                classified = bad['PCB'].nunique()
                functional = bad.loc[bad['FailureType'].eq('Functional Failure'), 'PCB'].nunique()
                rows.append({'Date': day, 'Input': n, 'FunctionPassRate': (n-functional)/n if n and classified<=n else None,
                             'SMTProcessNGRatePPM': classified/n*1e6 if n and classified<=n else None})
                usable.append({'Model': model, 'Date': day, 'Input': n})
            add(pd.DataFrame(rows), model, {'smt_function': 'FunctionPassRate', 'smt_process': 'SMTProcessNGRatePPM'},
                'Date', 'Input', smt['source_defect_start'], smt['source_defect_end'])
        inputs_by_area['SMT'] = pd.DataFrame(usable)
    if assembly is not None:
        inputs, defects = assembly['inputs'], assembly['defects']
        classified = defects[defects['FailureType'].isin(['Funcional', 'Aparência'])]
        recurrence.extend(collect_recurrences(prepared_recurrences(classified, 'Assembly'), 'Assembly', through))
        usable = []
        for model in ['All models', *sorted(inputs['Model'].unique())]:
            selected = inputs if model == 'All models' else inputs[inputs['Model'].eq(model)]
            bad = defects if model == 'All models' else defects[defects['Model'].eq(model)]
            result = assembly_kpi_v2.calculate_from_prepared(selected, bad, selected['Date'].min(), through)
            add(result['daily'], model, {'assembly_function': 'FunctionPassRate', 'assembly_appearance': 'AppearancePassRate',
                'assembly_mando': 'FunctionMandoPPM', 'smt_assembly_duty': 'SMTDutyPPM'},
                'Date', 'Input', assembly['source_defect_start'], assembly['source_defect_end'])
            usable.extend({'Model': model, 'Date': row.Date, 'Input': row.Input} for row in result['daily'].itertuples())
        inputs_by_area['Assembly'] = pd.DataFrame(usable)
    for area, records in inspections.items():
        production = inputs_by_area.get(area, pd.DataFrame())
        if records.empty or production.empty:
            continue
        for model in production['Model'].unique():
            selected = records if model == 'All models' else records[records['Model'].eq(model)]
            for day, group in selected.groupby('InspectionDate'):
                daily_input = production[production['Model'].eq(model) & production['Date'].eq(day)]['Input'].sum()
                if area == 'SMT':
                    n = group['Inspected'].sum()
                    value = group['OK'].sum()/n if n else None
                    source = 'smt_oqc'
                else:
                    oqc, fqc = group['OQCInspected'].sum(), group['FQCInspected'].sum()
                    value = group['OQCOK'].sum()/oqc * group['FQCOK'].sum()/fqc if oqc and fqc else None
                    source = 'assembly_oqc_fqc'
                if value is not None and not 0 <= value <= 1:
                    value = None
                points.append({'source': source, 'model': model, 'day': pd.Timestamp(day).date(), 'input': daily_input, 'value': value})
    return points, recurrence
