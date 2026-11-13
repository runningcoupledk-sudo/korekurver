#!/usr/bin/env python3
"""Bygger færdige vejnet-felter til apps'ene Kørekurver og Mødetid.

Læser et OpenStreetMap-udtræk (.osm.pbf, fx hele Danmark fra Geofabrik) og skriver ét lille
JSON-felt pr. ca. 9 x 9 km – samme inddeling som appen bruger. Appen henter så felterne direkte
herfra i stedet for at spørge de gratis Overpass-servere.

Brug:  python3 tools/byg_vejdata.py danmark.osm.pbf data/vej
"""
import sys, os, json, math, datetime, shutil
import osmium

FELT_LAT, FELT_LON = 0.08, 0.14      # skal passe med FELT_LAT / FELT_LON i appen
VEJE = {'motorway', 'motorway_link', 'trunk', 'trunk_link', 'primary', 'primary_link', 'secondary',
        'secondary_link', 'tertiary', 'tertiary_link', 'unclassified', 'residential', 'living_street'}


class Laeser(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.signaler = set()   # id på punkter med lyskryds
        self.veje = []          # (id, vejtype, maxspeed, oneway, junction, [punkt-id], [lat*1e6, lon*1e6, ...])
        self.forbud = []        # (id, tags, [(type, ref, rolle)])

    def node(self, n):
        if n.tags.get('highway') == 'traffic_signals':
            self.signaler.add(n.id)

    def way(self, w):
        hw = w.tags.get('highway')
        if hw not in VEJE or w.tags.get('area') == 'yes':
            return
        punkter, koord = [], []
        for n in w.nodes:
            if not n.location.valid():
                continue
            punkter.append(n.ref)
            koord.append(round(n.location.lat * 1e6))
            koord.append(round(n.location.lon * 1e6))
        if len(punkter) < 2:
            return
        self.veje.append((w.id, hw, w.tags.get('maxspeed', ''), w.tags.get('oneway', ''),
                          w.tags.get('junction', ''), punkter, koord))

    def relation(self, r):
        if r.tags.get('type') != 'restriction':
            return
        tags = {t.k: t.v for t in r.tags if t.k == 'type' or t.k == 'except' or t.k.startswith('restriction')}
        self.forbud.append((r.id, tags, [('way' if m.type == 'w' else 'node' if m.type == 'n' else 'relation', m.ref, m.role)
                                         for m in r.members]))


def felter_for_vej(koord):
    """Alle felter, som vejens stykker rører (også stykker der krydser et felt uden punkter i det)."""
    ud = set()
    for k in range(0, len(koord) - 2, 2):
        la1, lo1, la2, lo2 = koord[k] / 1e6, koord[k + 1] / 1e6, koord[k + 2] / 1e6, koord[k + 3] / 1e6
        for i in range(math.floor(min(la1, la2) / FELT_LAT), math.floor(max(la1, la2) / FELT_LAT) + 1):
            for j in range(math.floor(min(lo1, lo2) / FELT_LON), math.floor(max(lo1, lo2) / FELT_LON) + 1):
                ud.add((i, j))
    return ud


def main(pbf, ud_mappe):
    l = Laeser()
    try:   # springer alt uden vej- eller relationsmærker over (meget hurtigere); ældre pyosmium har ikke filtre
        l.apply_file(pbf, locations=True, idx='flex_mem', filters=[osmium.filter.KeyFilter('highway', 'type')])
    except (TypeError, AttributeError):
        l.apply_file(pbf, locations=True, idx='flex_mem')
    print(f'Læst: {len(l.veje)} veje, {len(l.signaler)} lyskryds, {len(l.forbud)} svingforbud', flush=True)

    felter = {}                      # (i, j) -> liste af vej-numre
    for nr, v in enumerate(l.veje):
        for f in felter_for_vej(v[6]):
            felter.setdefault(f, []).append(nr)
    forbud_for_vej = {}
    for nr, (_, _, medl) in enumerate(l.forbud):
        for t, ref, _ in medl:
            if t == 'way':
                forbud_for_vej.setdefault(ref, set()).add(nr)

    if os.path.isdir(ud_mappe):
        shutil.rmtree(ud_mappe)
    os.makedirs(ud_mappe)
    samlet = 0
    for (i, j), numre in felter.items():
        veje = [l.veje[n] for n in numre]
        sig = sorted({p for v in veje for p in v[5] if p in l.signaler})
        fnr = sorted({r for v in veje for r in forbud_for_vej.get(v[0], ())})
        data = {'v': 1,
                'w': [list(v) for v in veje],
                's': sig,
                'r': [[l.forbud[r][0], l.forbud[r][1], [list(m) for m in l.forbud[r][2]]] for r in fnr]}
        tekst = json.dumps(data, separators=(',', ':'), ensure_ascii=False)
        with open(os.path.join(ud_mappe, f'{i}_{j}.json'), 'w', encoding='utf-8') as fh:
            fh.write(tekst)
        samlet += len(tekst)
    indeks = {'v': 1, 'dato': datetime.date.today().isoformat(), 'kilde': 'OpenStreetMap-bidragydere (ODbL), udtræk fra Geofabrik',
              'feltLat': FELT_LAT, 'feltLon': FELT_LON, 'felter': sorted(f'{i}_{j}' for (i, j) in felter)}
    with open(os.path.join(ud_mappe, 'index.json'), 'w', encoding='utf-8') as fh:
        json.dump(indeks, fh, separators=(',', ':'))
    print(f'Skrev {len(felter)} felter, {samlet / 1e6:.0f} MB i alt', flush=True)


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
