"""Compare the previous and new site/data.json and describe notable changes, for phone alerts.

Usage: python alerts.py prev.json new.json out.md
Writes out.md (first line = title) only when something changed; prints the title.
Notable: confirmed regime change, a new raw regime signal starting its confirmation count,
a change in target allocation, an equity volatility spike starting or ending.
"""
import json, sys

URL = 'https://jbirnie209.github.io/strategy-dashboard/'
NAMES = ['S&P', 'Russell', '10Y', 'Gold', 'WTI', 'Cash']
EQ = {'spx': 'S&P 500', 'r2k': 'Russell 2000'}


def mix(w):
    return ' · '.join(f'{n} {x:.0%}' for n, x in zip(NAMES, w) if x > 0.0005) or 'none'


def main(prev_path, new_path, out_path):
    try:
        old = json.load(open(prev_path))['pulse']
    except (OSError, ValueError, KeyError):
        print('no previous data, nothing to compare')
        return
    new = json.load(open(new_path))['pulse']
    items, title = [], None
    if new['regime'] != old['regime']:
        title = f"Regime change: {old['regime']} → {new['regime']}"
        items.append(f"**Regime confirmed: {new['regime']}** (was {old['regime']}).")
    pn, po = new.get('pending'), old.get('pending')
    if pn and (not po or po['regime'] != pn['regime']):
        title = title or f"Regime signal: {pn['regime']} (day {pn['days']} of {pn['needed']})"
        items.append(f"Raw signal now reads **{pn['regime']}**: day {pn['days']} of {pn['needed']} needed to confirm.")
    elif po and not pn and new['regime'] == old['regime']:
        items.append(f"The {po['regime']} signal faded before confirming; regime stays {new['regime']}.")
    if any(abs(a - b) > 0.005 for a, b in zip(new['target'], old.get('target', []))) or len(new['target']) != len(old.get('target', [])):
        title = title or 'Allocation change'
        items.append(f"**Target allocation:** {mix(new['target'])} (was {mix(old['target'])}). "
                     f"Trades at the next close.")
    eq_n, eq_o = new.get('risk', {}).get('eq', {}), old.get('risk', {}).get('eq', {})
    for k, e in eq_n.items():
        was = eq_o.get(k, {}).get('spike')
        if was is not None and e['spike'] != was:
            title = title or f"{EQ[k]} volatility spike {'started' if e['spike'] else 'ended'}"
            items.append(f"{EQ[k]} 10-day vol {e['vol10']:.1%} vs trigger {e['trigger']:.1%}: "
                         f"spike {'started, exposure halved' if e['spike'] else 'ended'}.")
    if not items:
        print('no notable change')
        return
    body = '\n'.join(f'- {x}' for x in items)
    body += f"\n\nData to {new['asof']}. [Open the dashboard]({URL})"
    open(out_path, 'w').write(title + '\n' + body + '\n')
    print(title)


if __name__ == '__main__':
    main(*sys.argv[1:4])
