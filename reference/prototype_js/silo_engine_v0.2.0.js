/* Silo Decision Lab - independent discrete-event simulation engine.
   Runs headless (Node, Web Worker or page). No FlexSim dependency.
   Time unit: minutes from midnight. Rates: tonnes per hour. Quantities: tonnes (float).
   Event tie-breaking: time, then class (0 release/completion, 1 control, 2 arrival), then insertion order. */
(function (root) {
  'use strict';
  const VERSION = '0.2.0';
  const EPS = 1e-6;

  // ---------- random streams ----------
  function mulberry32(a) {
    return function () {
      a |= 0; a = (a + 0x6D2B79F5) | 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  function hash() {
    let h = 2166136261 >>> 0;
    for (let k = 0; k < arguments.length; k++) {
      const s = String(arguments[k]);
      for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619) >>> 0; }
      h ^= 0x2f; h = Math.imul(h, 16777619) >>> 0;
    }
    return h >>> 0;
  }
  function tri(u, p) {
    const a = +p[0], c = +p[1], b = +p[2];
    if (!(b > a)) return a;
    const F = (c - a) / (b - a);
    return u < F ? a + Math.sqrt(u * (b - a) * (c - a)) : b - Math.sqrt((1 - u) * (b - a) * (b - c));
  }
  const clone = (o) => JSON.parse(JSON.stringify(o));

  // ---------- event calendar ----------
  class Calendar {
    constructor() { this.a = []; this.seq = 0; }
    less(x, y) { return x.t < y.t || (x.t === y.t && (x.p < y.p || (x.p === y.p && x.s < y.s))); }
    push(t, p, fn, label) {
      const a = this.a; const e = { t, p, s: this.seq++, fn, label }; a.push(e);
      let i = a.length - 1;
      while (i > 0) { const j = (i - 1) >> 1; if (this.less(a[i], a[j])) { [a[i], a[j]] = [a[j], a[i]]; i = j; } else break; }
    }
    pop() {
      const a = this.a; if (!a.length) return null;
      const top = a[0]; const last = a.pop();
      if (a.length) {
        a[0] = last; let i = 0;
        for (;;) {
          const l = 2 * i + 1, r = l + 1; let m = i;
          if (l < a.length && this.less(a[l], a[m])) m = l;
          if (r < a.length && this.less(a[r], a[m])) m = r;
          if (m === i) break; [a[i], a[m]] = [a[m], a[i]]; i = m;
        }
      }
      return top;
    }
    get size() { return this.a.length; }
  }

  // ---------- equipment library ----------
  const TYPES = {
    sampler: { label: 'Sampling point', group: 'truck' },
    grader: { label: 'Grading station', group: 'truck' },
    weighbridge: { label: 'Weighbridge', group: 'truck' },
    hopper: { label: 'Unloading hopper', group: 'grain' },
    conveyor: { label: 'Conveyor', group: 'grain' },
    elevator: { label: 'Bucket elevator', group: 'grain' },
    bin: { label: 'Storage bin', group: 'grain' },
    loadpoint: { label: 'Loading point', group: 'grain' }
  };
  const CONNECT = {
    hopper: ['conveyor', 'elevator'],
    conveyor: ['conveyor', 'elevator', 'bin', 'loadpoint'],
    elevator: ['conveyor', 'bin', 'loadpoint'],
    bin: ['conveyor', 'elevator', 'loadpoint'],
    loadpoint: [], sampler: [], grader: [], weighbridge: []
  };
  const MID = (t) => t === 'conveyor' || t === 'elevator';
  const STEP_LABEL = { sample: 'Sampling', grade: 'Grading', weigh_in: 'Weigh in', tip: 'Unloading', load: 'Loading', weigh_out: 'Weigh out' };
  const ACT_LABEL = { unload: 'Unloading', load: 'Loading', weigh: 'Weighbridge only' };

  // ---------- validation ----------
  function nameOf(cfg, id) { const e = cfg.equipment.find((x) => x.id === id); return e ? e.name : id; }
  function cName(cfg, c) { const x = (cfg.commodities || []).find((k) => k.id === c); return x ? x.name : c; }
  function listNames(arr) { return arr.length <= 1 ? (arr[0] || '') : arr.slice(0, -1).join(', ') + ' and ' + arr[arr.length - 1]; }

  function buildRoutes(cfg) {
    const byId = {}; cfg.equipment.forEach((e) => { byId[e.id] = e; });
    const out = {}; cfg.equipment.forEach((e) => { out[e.id] = []; });
    (cfg.edges || []).forEach(([a, b]) => { if (out[a] && byId[b]) out[a].push(b); });
    const intake = {}, load = {};
    const LIMIT = 400;
    cfg.equipment.filter((e) => e.type === 'hopper').forEach((h) => {
      const paths = []; const stack = [[h.id, [h.id]]];
      while (stack.length && paths.length < LIMIT) {
        const [n, path] = stack.pop();
        for (const m of out[n]) {
          if (path.includes(m)) continue;
          const t = byId[m].type;
          if (t === 'bin') paths.push(path.concat(m));
          else if (MID(t)) stack.push([m, path.concat(m)]);
        }
      }
      paths.sort((a, b) => a.length - b.length || a.join().localeCompare(b.join()));
      intake[h.id] = paths;
    });
    cfg.equipment.filter((e) => e.type === 'bin').forEach((bn) => {
      const paths = []; const stack = [[bn.id, [bn.id]]];
      while (stack.length && paths.length < LIMIT) {
        const [n, path] = stack.pop();
        for (const m of out[n]) {
          if (path.includes(m)) continue;
          const t = byId[m].type;
          if (t === 'loadpoint') paths.push(path.concat(m));
          else if (MID(t)) stack.push([m, path.concat(m)]);
        }
      }
      paths.sort((a, b) => a.length - b.length || a.join().localeCompare(b.join()));
      load[bn.id] = paths;
    });
    return { intake, load, out, byId };
  }

  function validate(cfg) {
    const errors = [], warnings = [], info = [];
    const E = (msg, ids) => errors.push({ msg, ids: ids || [] });
    const W = (msg, ids) => warnings.push({ msg, ids: ids || [] });
    const eqs = cfg.equipment || [];
    const ids = new Set();
    eqs.forEach((e) => {
      if (ids.has(e.id)) E('Two items share the identifier ' + e.id + '. Each item needs its own identifier.', [e.id]);
      ids.add(e.id);
      if (!TYPES[e.type]) E(e.name + ' has an unsupported equipment type (' + e.type + ').', [e.id]);
    });
    const byId = {}; eqs.forEach((e) => { byId[e.id] = e; });
    const cids = new Set((cfg.commodities || []).map((c) => c.id));
    // edges
    const seen = new Set();
    (cfg.edges || []).forEach(([a, b]) => {
      if (!byId[a] || !byId[b]) { E('A connection refers to equipment that no longer exists (' + a + ' to ' + b + ').'); return; }
      const k = a + '>' + b;
      if (seen.has(k)) W('The connection from ' + byId[a].name + ' to ' + byId[b].name + ' is listed twice.', [a, b]);
      seen.add(k);
      if (!CONNECT[byId[a].type].includes(byId[b].type))
        E(byId[a].name + ' cannot feed ' + byId[b].name + '. A ' + TYPES[byId[a].type].label.toLowerCase() + ' cannot discharge into a ' + TYPES[byId[b].type].label.toLowerCase() + '.', [a, b]);
    });
    // capacities
    eqs.forEach((e) => {
      if (['sampler', 'grader', 'weighbridge'].includes(e.type)) {
        if (!(e.cap >= 1)) E(e.name + ' needs a capacity of at least 1 truck at a time.', [e.id]);
        if (!e.time || !(e.time[2] > 0)) E(e.name + ' needs a processing time.', [e.id]);
      }
      if (e.type === 'hopper') {
        if (!(e.capT > 0)) E(e.name + ' needs a pit capacity in tonnes.', [e.id]);
        if (!(e.rate > 0)) E(e.name + ' needs a discharge rate in t/h.', [e.id]);
        (e.commodities || []).forEach((c) => { if (!cids.has(c)) E(e.name + ' is assigned to an unknown commodity (' + c + ').', [e.id]); });
        if (!(e.commodities || []).length) W(e.name + ' accepts no commodity, so no truck will use it.', [e.id]);
      }
      if (MID(e.type) && !(e.rate > 0)) E(e.name + ' needs a transfer rate in t/h.', [e.id]);
      if (e.type === 'loadpoint' && !(e.rate > 0)) E(e.name + ' needs a loading rate in t/h.', [e.id]);
      if (e.type === 'bin') {
        if (!(e.capT > 0)) E(e.name + ' needs a capacity in tonnes.', [e.id]);
        if ((e.inv || 0) > (e.capT || 0) + EPS) E(e.name + ' holds ' + e.inv + ' t at the start, more than its ' + e.capT + ' t capacity.', [e.id]);
        if ((e.inv || 0) > 0 && !(e.commodities || []).includes(e.invCommodity))
          E(e.name + ' starts with ' + cName(cfg, e.invCommodity) + ', which the bin is not allowed to store.', [e.id]);
      }
    });
    const R = buildRoutes(cfg);
    // cycles among transfer equipment (bins break a cycle legitimately)
    const mids = eqs.filter((e) => MID(e.type) || e.type === 'hopper').map((e) => e.id);
    const color = {}; let cycleAt = null;
    const dfs = (n) => {
      color[n] = 1;
      for (const m of R.out[n] || []) {
        if (!byId[m] || !(MID(byId[m].type))) continue;
        if (color[m] === 1) { cycleAt = cycleAt || [n, m]; continue; }
        if (!color[m]) dfs(m);
      }
      color[n] = 2;
    };
    mids.forEach((n) => { if (!color[n]) dfs(n); });
    if (cycleAt) E('Grain could circulate in a loop between ' + byId[cycleAt[0]].name + ' and ' + byId[cycleAt[1]].name + '. Remove one of the connections in that loop.', cycleAt);

    // truck sequences
    const seqs = cfg.sequences || {};
    const has = (t, pred) => eqs.some((e) => e.type === t && (!pred || pred(e)));
    const dem = cfg.demand || {};
    Object.keys(ACT_LABEL).forEach((act) => {
      const d = dem[act]; if (!d || !(d.daily > 0)) return;
      const s = seqs[act] || [];
      if (!s.length) E(ACT_LABEL[act] + ' trucks have no activity sequence.');
      s.forEach((st, i) => {
        if (st === 'sample' && !has('sampler')) E(ACT_LABEL[act] + ' trucks need a sampling point, but none is configured.');
        if (st === 'grade') {
          if (!has('grader')) E(ACT_LABEL[act] + ' trucks need a grading station, but none is configured.');
          if (s.indexOf('sample') < 0 || s.indexOf('sample') > i) E(ACT_LABEL[act] + ' trucks are graded before a sample is taken. Put Sampling before Grading.');
        }
        if (st === 'weigh_in' && !has('weighbridge', (e) => e.moves !== 'out')) E(ACT_LABEL[act] + ' trucks need a weighbridge that weighs in.');
        if (st === 'weigh_out' && !has('weighbridge', (e) => e.moves !== 'in')) E(ACT_LABEL[act] + ' trucks need a weighbridge that weighs out.');
        if (st === 'tip' && act !== 'unload') E('Only unloading trucks can tip into a hopper.');
        if (st === 'load' && act !== 'load') E('Only loading trucks can be loaded.');
      });
      if (act === 'unload' && !s.includes('tip')) E('Unloading trucks never reach a hopper. Add Unloading to their sequence.');
      if (act === 'load' && !s.includes('load')) E('Loading trucks never reach a loading point. Add Loading to their sequence.');
    });

    // hopper reachability and commodity routing
    const hoppers = eqs.filter((e) => e.type === 'hopper');
    const bins = eqs.filter((e) => e.type === 'bin');
    hoppers.forEach((h) => {
      const paths = R.intake[h.id] || [];
      if (!(R.out[h.id] || []).length) { E(h.name + ' is not connected to any conveyor or elevator, so grain tipped there cannot leave the pit.', [h.id]); return; }
      if (!paths.length) { E(h.name + ' has no complete route to a storage bin. Follow its conveyors and elevators and connect the last one to a bin.', [h.id]); return; }
      const reach = [...new Set(paths.map((p) => p[p.length - 1]))];
      (h.commodities || []).forEach((c) => {
        const ok = reach.some((b) => (byId[b].commodities || []).includes(c));
        if (ok) return;
        const accepting = bins.filter((b) => (b.commodities || []).includes(c)).map((b) => b.name);
        const lastHops = [...new Set(paths.map((p) => byId[p[p.length - 2]].name))];
        if (!accepting.length) E(h.name + ' accepts ' + cName(cfg, c) + ', but no storage bin is allowed to hold ' + cName(cfg, c) + '.', [h.id]);
        else E(h.name + ' cannot deliver ' + cName(cfg, c) + ' to any eligible storage bin because ' + listNames(lastHops) + ' ' + (lastHops.length > 1 ? 'are' : 'is') + ' not connected to ' + listNames(accepting) + '.', [h.id]);
      });
    });
    bins.forEach((b) => {
      const reachedBy = hoppers.filter((h) => (R.intake[h.id] || []).some((p) => p[p.length - 1] === b.id));
      if (!reachedBy.length) W(b.name + ' cannot receive grain from any hopper.', [b.id]);
    });
    // commodity demand coverage
    const un = dem.unload;
    if (un && un.daily > 0) {
      const mix = un.mix || {}; const tot = Object.values(mix).reduce((a, b) => a + (+b || 0), 0);
      if (Math.abs(tot - 1) > 0.01) W('The unloading commodity mix adds up to ' + Math.round(tot * 100) + '%. It will be scaled to 100%.');
      Object.keys(mix).forEach((c) => {
        if (!(mix[c] > 0)) return;
        if (!cids.has(c)) { E('Unloading demand includes an unknown commodity (' + c + ').'); return; }
        const hs = hoppers.filter((h) => (h.commodities || []).includes(c));
        if (!hs.length) E(cName(cfg, c) + ' trucks arrive, but no hopper accepts ' + cName(cfg, c) + '.');
      });
      if (!(un.payload && un.payload[2] > 0)) E('Unloading trucks need a payload range in tonnes.');
      const maxHopper = Math.max(0, ...hoppers.map((h) => h.capT || 0));
      if (un.payload && un.payload[2] > maxHopper + EPS) E('The largest unloading payload (' + un.payload[2] + ' t) exceeds every hopper capacity (largest ' + maxHopper + ' t).');
    }
    const ld = dem.load;
    if (ld && ld.daily > 0) {
      const mix = ld.mix || {};
      Object.keys(mix).forEach((c) => {
        if (!(mix[c] > 0)) return;
        const bs = bins.filter((b) => (b.commodities || []).includes(c));
        const feasible = bs.filter((b) => (R.load[b.id] || []).length);
        if (!bs.length) E('Loading trucks collect ' + cName(cfg, c) + ', but no bin stores it.');
        else if (!feasible.length) E('Loading trucks collect ' + cName(cfg, c) + ', but no bin holding it is connected to a loading point.');
        else {
          const stock = feasible.reduce((a, b) => a + (b.invCommodity === c ? (b.inv || 0) : 0), 0);
          const fedByIntake = un && un.daily > 0 && (un.mix || {})[c] > 0;
          if (stock < (ld.payload ? ld.payload[2] : 30) && !fedByIntake) E('Loading trucks collect ' + cName(cfg, c) + ', but there is no opening stock and no intake of it.');
          else if (stock < (ld.payload ? ld.payload[2] : 30)) W('There is little opening stock of ' + cName(cfg, c) + '. Early loading trucks will wait for intake.');
        }
      });
    }
    // shared equipment
    const users = {};
    hoppers.forEach((h) => (R.intake[h.id] || []).forEach((p) => p.slice(1, -1).forEach((m) => { (users[m] = users[m] || new Set()).add(h.name); })));
    bins.forEach((b) => (R.load[b.id] || []).forEach((p) => p.slice(1, -1).forEach((m) => { (users[m] = users[m] || new Set()).add('loading'); })));
    const shared = Object.keys(users).filter((k) => users[k].size > 1);
    shared.forEach((k) => info.push({ msg: byId[k].name + ' is shared by ' + listNames([...users[k]]) + '. Only one grain stream can use it at a time.', ids: [k] }));
    const wbShared = eqs.filter((e) => e.type === 'weighbridge');
    const acts = Object.keys(ACT_LABEL).filter((a) => dem[a] && dem[a].daily > 0);
    if (wbShared.length && acts.length > 1) info.push({ msg: 'Weighbridge capacity is shared by ' + listNames(acts.map((a) => ACT_LABEL[a].toLowerCase())) + ' trucks.', ids: wbShared.map((e) => e.id) });
    const unreachable = bins.filter((b) => !hoppers.some((h) => (R.intake[h.id] || []).some((p) => p[p.length - 1] === b.id))).map((b) => b.id);
    return { ok: errors.length === 0, errors, warnings, info, routes: R, shared, users: Object.fromEntries(Object.entries(users).map(([k, v]) => [k, [...v]])), unreachable };
  }

  // ---------- simulation ----------
  function runReplication(cfg, opt) {
    opt = opt || {};
    const v = opt.validation || validate(cfg);
    if (!v.ok) throw new Error('Configuration is not valid: ' + v.errors[0].msg);
    const seed = (opt.seed >>> 0) || 1;
    const df = opt.demandFactor == null ? 1 : +opt.demandFactor;
    const warm = (opt.warmup || 0);
    const traceOn = !!opt.trace;
    const R = v.routes;
    const hrs = cfg.hours || { open: 6, close: 18, overtime: 3 };
    const T0 = hrs.open * 60, TC = hrs.close * 60, TEND = (hrs.close + (hrs.overtime || 0)) * 60;
    const pol = Object.assign({ tip: 'fifo', weigh: 'fifo', transfer: 'fifo' }, cfg.policies || {});
    const cal = new Calendar();
    let now = T0;
    const diag = []; const trace = [];
    const fail = (rule, msg, ents, res) => { if (diag.length < 200) diag.push({ t: now, rule, msg, entities: ents || [], resources: res || [] }); };
    const log = (msg) => { if (traceOn && trace.length < 3000) trace.push([now, msg]); };

    // state
    const S = {}; // equipment state
    cfg.equipment.forEach((e) => {
      S[e.id] = { e, busy: 0, area: 0, lastT: T0, last: null, level: 0, lots: [], hC: null, tipping: false, transferring: false,
        inv: e.type === 'bin' ? (e.inv || 0) : 0, invC: e.type === 'bin' && e.inv > 0 ? e.invCommodity : null,
        resIn: 0, resInC: null, resOut: 0, waitArea: 0, waitLast: T0, waiting: false, changeovers: 0, transfers: 0, tons: 0 };
      if (e.type === 'hopper' && e.level0 > 0) {
        S[e.id].level = e.level0; S[e.id].hC = e.levelCommodity;
        S[e.id].lots.push({ id: 'L0-' + e.id, truck: null, c: e.levelCommodity, rem: e.level0, qty: e.level0, t: T0 });
      }
    });
    const eqOf = (t) => cfg.equipment.filter((e) => e.type === t);
    const setBusy = (id, d) => { const s = S[id]; s.area += s.busy * (now - s.lastT); s.lastT = now; s.busy += d;
      const cap = s.e.cap || 1; if (s.busy > cap + EPS || s.busy < -EPS) fail('double-allocation', s.e.name + ' was allocated beyond its capacity (' + s.busy + ' of ' + cap + ').', [], [id]); };
    const setWaiting = (id, w) => { const s = S[id]; if (s.waiting) s.waitArea += now - s.waitLast; s.waitLast = now; s.waiting = w; };
    let opening = 0; cfg.equipment.forEach((e) => { opening += S[e.id].inv + S[e.id].level; });
    let received = 0, dispatched = 0, stored = 0;

    // units for pooled truck resources
    const units = { sample: [], grade: [], weigh: [] };
    eqOf('sampler').forEach((e) => { for (let k = 0; k < e.cap; k++) units.sample.push({ id: e.id, k, busy: false }); });
    eqOf('grader').forEach((e) => { for (let k = 0; k < e.cap; k++) units.grade.push({ id: e.id, k, busy: false }); });
    eqOf('weighbridge').forEach((e) => { for (let k = 0; k < e.cap; k++) units.weigh.push({ id: e.id, k, busy: false, moves: e.moves || 'both' }); });

    // queues with time-weighted stats
    const Q = {};
    ['sample', 'grade', 'weigh', 'tip', 'load'].forEach((k) => { Q[k] = { items: [], area: 0, last: T0, max: 0 }; });
    const qTouch = (k) => { const q = Q[k]; q.area += q.items.length * (now - q.last); q.last = now; };
    const qPush = (k, x) => { qTouch(k); Q[k].items.push(x); Q[k].max = Math.max(Q[k].max, Q[k].items.length); };
    const qTake = (k, i) => { qTouch(k); return Q[k].items.splice(i, 1)[0]; };

    // trucks
    const trucks = {}; const present = new Set();
    const done = []; const rejected = [];
    const gradeResults = {}; // sampleId -> {reject}
    const awaiting = {}; // truckId -> sampleId
    const transfersLog = {}; const lotsDone = [];
    let tCount = 0;
    const commodityPick = (mix, u) => {
      const ks = Object.keys(mix).filter((k) => mix[k] > 0); const tot = ks.reduce((a, k) => a + +mix[k], 0);
      let acc = 0; for (const k of ks) { acc += mix[k] / tot; if (u < acc) return k; } return ks[ks.length - 1];
    };
    function makeTruck(act, idx, arr, backlog) {
      const r = mulberry32(hash(seed, act, idx, backlog ? 'b' : 'a'));
      const d = cfg.demand[act];
      const tr = { id: (act === 'unload' ? 'U' : act === 'load' ? 'L' : 'W') + (backlog ? 'B' : '') + idx, act, arr, steps: (cfg.sequences[act] || []).slice(), si: -1,
        u: {}, waits: {}, svc: {}, qIn: 0, c: null, qty: 0, grade: null, backlog: !!backlog };
      const u1 = r(), u2 = r();
      if (act !== 'weigh') { tr.c = commodityPick(d.mix || {}, u1); tr.qty = Math.round(tri(u2, d.payload) * 100) / 100; }
      tr.grade = act === 'unload' ? (r() < 0.85 ? 'Grade 1' : 'Grade 2') : null;
      ['sample', 'grade', 'weigh_in', 'tip', 'load', 'weigh_out', 'reject', 'setup'].forEach((k) => { tr.u[k] = r(); });
      tCount++;
      return tr;
    }
    function arrive(tr) {
      trucks[tr.id] = tr; present.add(tr.id); log(tr.id + ' arrives (' + ACT_LABEL[tr.act] + (tr.c ? ', ' + cName(cfg, tr.c) + ' ' + tr.qty + ' t' : '') + ')');
      advance(tr);
    }
    function depart(tr, rej) {
      tr.dep = now; present.delete(tr.id);
      // completion invariant
      if (!rej && tr.si !== tr.steps.length) fail('truck-completion', tr.id + ' left before completing its activity sequence.', [tr.id]);
      (rej ? rejected : done).push(tr); log(tr.id + (rej ? ' rejected and leaves' : ' departs'));
    }
    function advance(tr) {
      tr.si++;
      if (tr.si >= tr.steps.length) { depart(tr, false); return; }
      const st = tr.steps[tr.si]; tr.qIn = now; tr.cur = st;
      if (st === 'sample') { qPush('sample', tr); dispatchPool('sample'); }
      else if (st === 'grade') {
        const sid = 'S' + tr.id;
        if (gradeResults[sid]) { finishGradeWait(tr, gradeResults[sid]); }
        else awaiting[tr.id] = sid;
      }
      else if (st === 'weigh_in' || st === 'weigh_out') { tr.dir = st === 'weigh_in' ? 'in' : 'out'; qPush('weigh', tr); dispatchPool('weigh'); }
      else if (st === 'tip') { qPush('tip', tr); dispatchTip(); }
      else if (st === 'load') { qPush('load', tr); dispatchTransfers(); }
    }
    function finishGradeWait(tr, res) {
      tr.waits.grade = (tr.waits.grade || 0) + (now - tr.qIn);
      delete awaiting[tr.id];
      if (res.reject) { depart(tr, true); return; }
      tr.gradedAs = res.grade; advance(tr);
    }

    // pooled resources: samplers, graders (samples), weighbridges
    function unitFits(kind, unit, item) {
      if (unit.busy) return false;
      if (kind === 'weigh') return unit.moves === 'both' || unit.moves === item.dir;
      return true;
    }
    function weighOrder(items) {
      const idx = items.map((x, i) => i);
      if (pol.weigh === 'load_first') idx.sort((a, b) => (items[a].act === 'load' ? 0 : 1) - (items[b].act === 'load' ? 0 : 1) || a - b);
      else if (pol.weigh === 'out_first') idx.sort((a, b) => (items[a].dir === 'out' ? 0 : 1) - (items[b].dir === 'out' ? 0 : 1) || a - b);
      return idx;
    }
    function dispatchPool(kind) {
      let progress = true;
      while (progress) {
        progress = false;
        const items = Q[kind].items;
        const order = kind === 'weigh' ? weighOrder(items) : items.map((x, i) => i);
        for (const i of order) {
          const item = items[i];
          const unit = units[kind].find((u) => unitFits(kind, u, item));
          if (unit) { qTake(kind, i); startPool(kind, item, unit); progress = true; break; }
        }
      }
    }
    function startPool(kind, item, unit) {
      unit.busy = true; setBusy(unit.id, 1);
      const e = S[unit.id].e;
      let dur;
      if (kind === 'grade') { dur = tri(item.u, e.time); item.wait = now - item.qIn; }
      else {
        const key = kind === 'weigh' ? (item.dir === 'in' ? 'weigh_in' : 'weigh_out') : 'sample';
        dur = tri(item.u[key], e.time); item.waits[key] = (item.waits[key] || 0) + (now - item.qIn); item.svc[key] = dur;
        if (key === 'weigh_in') item.wbIn = now;
      }
      log((kind === 'grade' ? 'Sample ' + item.id : item.id) + ' starts ' + (kind === 'grade' ? 'grading' : kind === 'weigh' ? (item.dir === 'in' ? 'weigh-in' : 'weigh-out') : 'sampling') + ' at ' + e.name);
      cal.push(now + dur, 0, () => {
        unit.busy = false; setBusy(unit.id, -1);
        if (kind === 'sample') {
          const smp = { id: 'S' + item.id, truckId: item.id, qIn: now, u: item.u.grade, reject: item.u.reject };
          qPush('grade', smp); dispatchPool('grade');
          advance(item);
          dispatchPool('sample');
        } else if (kind === 'grade') {
          const g = S[unit.id].e;
          const res = { reject: item.reject < (g.reject || 0), grade: trucks[item.truckId] ? trucks[item.truckId].grade : null };
          const tr = trucks[item.truckId];
          if (!tr) { fail('sample-match', 'Sample ' + item.id + ' has no matching truck.', [item.id]); }
          else if (awaiting[tr.id] === item.id) finishGradeWait(tr, res);
          else if (awaiting[tr.id] && awaiting[tr.id] !== item.id) fail('sample-match', 'Sample ' + item.id + ' was offered to truck ' + tr.id + ', which waits for ' + awaiting[tr.id] + '.', [item.id, tr.id]);
          else gradeResults[item.id] = res;
          dispatchPool('grade');
        } else {
          if (item.dir === 'out') item.wbOut = now;
          advance(item);
          dispatchPool('weigh');
        }
      }, kind + ' done');
    }

    // hoppers
    const hoppers = eqOf('hopper').map((e) => S[e.id]);
    const routable = {}; // hopperId -> Set(commodity) that can reach an accepting bin
    hoppers.forEach((h) => {
      routable[h.e.id] = new Set();
      (R.intake[h.e.id] || []).forEach((p) => (S[p[p.length - 1]].e.commodities || []).forEach((c) => routable[h.e.id].add(c)));
    });
    function hopperFits(h, tr) {
      return !h.tipping && (h.e.commodities || []).includes(tr.c) && routable[h.e.id].has(tr.c) &&
        (h.level < EPS || h.hC === tr.c) && (h.e.capT - h.level) >= tr.qty - EPS;
    }
    function dispatchTip() {
      let progress = true;
      while (progress) {
        progress = false;
        const items = Q.tip.items; if (!items.length) return;
        if (pol.tip === 'batch') {
          // each free hopper takes the earliest truck matching its current commodity, else the earliest feasible truck
          for (const h of hoppers) {
            if (h.tipping) continue;
            const ref = h.level > EPS ? h.hC : h.last;
            let i = items.findIndex((tr) => tr.c === ref && hopperFits(h, tr));
            if (i < 0) i = items.findIndex((tr) => hopperFits(h, tr));
            if (i >= 0) { startTip(h, qTake('tip', i)); progress = true; break; }
          }
        } else {
          const lim = pol.tip === 'fifo' ? 1 : items.length;
          for (let i = 0; i < lim; i++) {
            const tr = items[i];
            const h = hoppers.find((x) => hopperFits(x, tr) && x.level > EPS && x.hC === tr.c) || hoppers.find((x) => hopperFits(x, tr));
            if (h) { startTip(h, qTake('tip', i)); progress = true; break; }
          }
        }
      }
    }
    function startTip(h, tr) {
      h.tipping = true; setBusy(h.e.id, 1);
      if (h.level < EPS) h.hC = tr.c;
      if (h.hC !== tr.c) fail('commodity-mixing', tr.id + ' tipped ' + cName(cfg, tr.c) + ' into ' + h.e.name + ', which holds ' + cName(cfg, h.hC) + '.', [tr.id], [h.e.id]);
      h.level += tr.qty; h.reservedFor = tr.id; // pit space is claimed at the start of tipping
      tr.waits.tip = (tr.waits.tip || 0) + (now - tr.qIn); tr.hopper = h.e.id;
      const dur = tri(tr.u.tip, h.e.tip || [4, 6, 9]); tr.svc.tip = dur;
      log(tr.id + ' starts tipping ' + tr.qty + ' t into ' + h.e.name);
      cal.push(now + dur, 0, () => {
        h.tipping = false; setBusy(h.e.id, -1);
        received += tr.qty;
        const lot = { id: 'G' + tr.id, truck: tr.id, c: tr.c, grade: tr.grade, qty: tr.qty, rem: tr.qty, t: now, src: h.e.id };
        h.lots.push(lot); if (!h.transferring) setWaiting(h.e.id, true);
        log('Grain lot ' + lot.id + ' (' + lot.qty + ' t) waits in ' + h.e.name);
        advance(tr); dispatchTransfers(); dispatchTip();
      }, 'tip done');
    }

    // grain transfers (intake and loading) over shared route equipment
    const routeFree = (p) => p.slice(1, -1).every((m) => S[m].busy === 0);
    const changeoverOf = (p, c) => p.slice(1, -1).reduce((mx, m) => Math.max(mx, S[m].last && S[m].last !== c ? (S[m].e.changeover || 0) : 0), 0);
    const routeRate = (p) => Math.min(...p.map((m) => (S[m].e.type === 'bin' ? Infinity : S[m].e.rate || Infinity)));
    function binAccepts(b, c) {
      return (b.e.commodities || []).includes(c) && (b.invC == null || b.invC === c) && (b.resInC == null || b.resInC === c) &&
        (b.e.capT - b.inv - b.resIn) > EPS;
    }
    function tryIntake(h) {
      const lot = h.lots[0]; if (!lot) return false;
      const paths = (R.intake[h.e.id] || []).filter((p) => binAccepts(S[p[p.length - 1]], lot.c) && routeFree(p));
      if (!paths.length) return false;
      const batchPref = pol.transfer === 'batch';
      paths.sort((a, b) => {
        const ba = S[a[a.length - 1]], bb = S[b[b.length - 1]];
        const fa = ba.invC === lot.c ? 0 : 1, fb = bb.invC === lot.c ? 0 : 1;
        const ca = changeoverOf(a, lot.c) > 0 ? 1 : 0, cb = changeoverOf(b, lot.c) > 0 ? 1 : 0;
        return (batchPref ? (ca - cb) || (fa - fb) : (fa - fb) || (ca - cb)) || a.length - b.length;
      });
      const p = paths[0]; const bin = S[p[p.length - 1]];
      const amt = Math.min(lot.rem, bin.e.capT - bin.inv - bin.resIn);
      const co = changeoverOf(p, lot.c);
      const dur = co + amt / routeRate(p) * 60;
      startTransfer('in', p, lot.c, amt, dur, co, () => {
        bin.inv += amt; if (bin.invC && bin.invC !== lot.c) fail('commodity-mixing', lot.c + ' entered ' + bin.e.name + ', which holds ' + bin.invC + '.', [lot.id], [bin.e.id]);
        bin.invC = lot.c; bin.resIn -= amt; if (bin.resIn < EPS) { bin.resIn = 0; bin.resInC = null; }
        lot.rem -= amt; h.level -= amt; stored += amt;
        if (h.level < EPS) { h.level = 0; }
        if (lot.rem < EPS) { h.lots.shift(); lot.stored = now; lotsDone.push(lot); log('Grain lot ' + lot.id + ' reaches storage in ' + bin.e.name); }
        h.transferring = false; h.last = lot.c; if (h.lots.length) setWaiting(h.e.id, true);
      }, () => { bin.resIn += amt; bin.resInC = lot.c; h.transferring = true; setWaiting(h.e.id, false); log('Transfer ' + amt.toFixed(2) + ' t ' + cName(cfg, lot.c) + ': ' + p.map((m) => S[m].e.name).join(' > ') + (co ? ' (changeover ' + co + ' min)' : '')); });
      return true;
    }
    function tryLoad(i) {
      const tr = Q.load.items[i];
      const lps = eqOf('loadpoint').map((e) => S[e.id]).filter((l) => l.busy === 0);
      if (!lps.length) return false;
      const cands = [];
      cfg.equipment.filter((e) => e.type === 'bin').forEach((be) => {
        const b = S[be.id]; if (b.invC !== tr.c || b.inv - b.resOut < tr.qty - EPS) return;
        (R.load[be.id] || []).forEach((p) => { if (S[p[p.length - 1]].busy === 0 && routeFree(p)) cands.push(p); });
      });
      if (!cands.length) return false;
      cands.sort((a, b) => (changeoverOf(a, tr.c) - changeoverOf(b, tr.c)) || a.length - b.length);
      const p = cands[0]; const bin = S[p[0]]; const lp = S[p[p.length - 1]];
      qTake('load', i);
      tr.waits.load = (tr.waits.load || 0) + (now - tr.qIn);
      const co = changeoverOf(p, tr.c);
      const setup = tri(tr.u.setup, lp.e.setup || [3, 5, 8]);
      const dur = setup + co + tr.qty / routeRate(p) * 60; tr.svc.load = dur;
      startTransfer('out', p, tr.c, tr.qty, dur, co, () => {
        bin.inv -= tr.qty; bin.resOut -= tr.qty; dispatched += tr.qty;
        if (bin.inv < -EPS) fail('negative-inventory', bin.e.name + ' fell below zero.', [tr.id], [bin.e.id]);
        if (bin.inv < EPS) { bin.inv = 0; bin.invC = null; }
        log(tr.id + ' loaded ' + tr.qty + ' t from ' + bin.e.name);
        advance(tr);
      }, () => { bin.resOut += tr.qty; log(tr.id + ' starts loading from ' + bin.e.name + ' via ' + p.slice(1).map((m) => S[m].e.name).join(' > ')); }, true);
      return true;
    }
    function startTransfer(kind, p, c, amt, dur, co, onEnd, onStart, includeLast) {
      const res = includeLast ? p.slice(1) : p.slice(1, -1);
      const key = p.join('>');
      const allowed = kind === 'in' ? (R.intake[p[0]] || []) : (R.load[p[0]] || []);
      if (!allowed.some((q) => q.join('>') === key)) fail('unsupported-route', 'Grain moved along ' + key + ', which is not a configured route.', [], p);
      res.forEach((m) => { if (S[m].busy !== 0) fail('route-overlap', S[m].e.name + ' was given to two grain streams at once.', [], [m]); setBusy(m, 1); if (S[m].last && S[m].last !== c && MID(S[m].e.type)) S[m].changeovers++; });
      onStart();
      const k2 = p[0] + '>' + p[p.length - 1];
      transfersLog[k2] = (transfersLog[k2] || 0) + amt;
      cal.push(now + dur, 0, () => {
        res.forEach((m) => { setBusy(m, -1); S[m].last = c; S[m].transfers++; S[m].tons += amt; });
        onEnd();
        balanceCheck();
        dispatchTransfers(); dispatchTip();
      }, 'transfer done');
    }
    function dispatchTransfers() {
      let progress = true; let guard = 0;
      while (progress && guard++ < 500) {
        progress = false;
        const cands = [];
        hoppers.forEach((h) => { if (h.lots.length && !h.transferring) cands.push({ k: 'in', h, since: h.lots[0].t, c: h.lots[0].c }); });
        Q.load.items.forEach((tr, i) => cands.push({ k: 'out', i, since: tr.qIn, c: tr.c }));
        if (pol.transfer === 'load_first') cands.sort((a, b) => (a.k === 'out' ? 0 : 1) - (b.k === 'out' ? 0 : 1) || a.since - b.since);
        else cands.sort((a, b) => a.since - b.since);
        for (const cd of cands) {
          if (cd.k === 'in' ? tryIntake(cd.h) : tryLoad(cd.i)) { progress = true; break; }
        }
      }
    }
    function balanceCheck() {
      let closing = 0;
      cfg.equipment.forEach((e) => { closing += S[e.id].inv + S[e.id].level; });
      // grain inside a truck that is still tipping is counted in the hopper level but not yet received
      let tippingQty = 0; hoppers.forEach((h) => { if (h.tipping) { const tr = trucks[h.reservedFor]; if (tr) tippingQty += tr.qty; } });
      const err = opening + received - dispatched - (closing - tippingQty);
      if (Math.abs(err) > 1e-6) fail('material-balance', 'Grain is unaccounted for: ' + err.toFixed(6) + ' t.', [], []);
      cfg.equipment.forEach((e) => { if (S[e.id].inv < -EPS) fail('negative-inventory', e.name + ' has negative stock.', [], [e.id]); });
      return err;
    }

    // ---------- arrivals ----------
    const hourly = { unload: new Array(24).fill(0), load: new Array(24).fill(0), weigh: new Array(24).fill(0) };
    Object.keys(ACT_LABEL).forEach((act) => {
      const d = (cfg.demand || {})[act]; if (!d || !(d.daily > 0)) return;
      const prof = d.profile && d.profile.length === 24 ? d.profile : new Array(24).fill(1);
      const tot = prof.reduce((a, h, i) => a + (i >= hrs.open && i < hrs.close ? +h : 0), 0) || 1;
      const r = mulberry32(hash(seed, 'arrivals', act));
      let t = T0, idx = 0;
      while (t < TC) {
        const h = Math.floor(t / 60);
        const lam = d.daily * df * (prof[h] || 0) / tot; // trucks per hour
        const hourEnd = (h + 1) * 60;
        if (!(lam > 0)) { t = hourEnd; continue; }
        const dt = -Math.log(1 - r()) / lam * 60;
        if (t + dt >= hourEnd) { t = hourEnd; continue; }
        t += dt; if (t >= TC) break;
        const at = t; const tr = makeTruck(act, idx++, at, false);
        hourly[act][Math.floor(at / 60)]++;
        cal.push(at, 2, () => arrive(tr), 'arrival');
      }
      const back = ((cfg.initial || {}).queue || {})[act] || 0;
      for (let b = 0; b < back; b++) { const tr = makeTruck(act, b, T0, true); cal.push(T0, 1, () => arrive(tr), 'backlog'); }
    });
    cal.push(TEND, 1, () => { stop = true; }, 'end');

    // ---------- main loop ----------
    let stop = false; let events = 0;
    dispatchTransfers();
    while (!stop) {
      const ev = cal.pop(); if (!ev) break;
      if (ev.t < now - EPS) fail('clock', 'An event was scheduled in the past.', [], []);
      now = ev.t; events++;
      ev.fn();
      if (events > 2e6) { fail('runaway', 'Simulation exceeded 2 million events.', [], []); break; }
    }
    // close accounting
    now = Math.max(now, T0);
    Object.keys(S).forEach((id) => { const s = S[id]; s.area += s.busy * (now - s.lastT); s.lastT = now; if (s.waiting) { s.waitArea += now - s.waitLast; s.waitLast = now; } });
    Object.keys(Q).forEach(qTouch);
    const balErr = balanceCheck();

    // ---------- metrics ----------
    const span = now - T0 || 1;
    const stats = (arr) => {
      if (!arr.length) return { n: 0, mean: null, median: null, p90: null, p95: null, max: null };
      const s = arr.slice().sort((a, b) => a - b); const q = (p) => s[Math.min(s.length - 1, Math.floor(p * (s.length - 1) + 0.5))];
      return { n: s.length, mean: s.reduce((a, b) => a + b, 0) / s.length, median: q(0.5), p90: q(0.9), p95: q(0.95), max: s[s.length - 1] };
    };
    const counted = done.filter((t) => t.arr >= T0 + warm);
    const tat = {}; ['unload', 'load', 'weigh'].forEach((a) => { tat[a] = stats(counted.filter((t) => t.act === a).map((t) => t.dep - t.arr)); });
    tat.all = stats(counted.map((t) => t.dep - t.arr));
    const wbio = stats(counted.filter((t) => t.act === 'unload' && t.wbIn != null && t.wbOut != null).map((t) => t.wbOut - t.wbIn));
    const waits = {};
    ['sample', 'grade', 'weigh_in', 'tip', 'load', 'weigh_out'].forEach((k) => {
      const xs = counted.filter((t) => t.waits[k] != null).map((t) => t.waits[k]);
      waits[k] = xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null;
    });
    const waitsByAct = {};
    ['unload', 'load', 'weigh'].forEach((a) => {
      waitsByAct[a] = {};
      ['sample', 'grade', 'weigh_in', 'tip', 'load', 'weigh_out'].forEach((k) => {
        const xs = counted.filter((t) => t.act === a && t.waits[k] != null).map((t) => t.waits[k]);
        if (xs.length) waitsByAct[a][k] = xs.reduce((x, y) => x + y, 0) / xs.length;
      });
    });
    const queues = {}; Object.keys(Q).forEach((k) => { queues[k] = { avg: Q[k].area / span, max: Q[k].max, end: Q[k].items.length }; });
    const util = {}; const blocked = {}; const changeovers = {}; const tons = {};
    cfg.equipment.forEach((e) => {
      const s = S[e.id];
      if (['sampler', 'grader', 'weighbridge'].includes(e.type)) util[e.id] = s.area / (span * (e.cap || 1));
      else if (e.type !== 'bin') util[e.id] = s.area / span;
      if (e.type === 'hopper') blocked[e.id] = s.waitArea;
      if (MID(e.type)) { changeovers[e.id] = s.changeovers; tons[e.id] = s.tons; }
    });
    const commodity = {};
    counted.filter((t) => t.c).forEach((t) => {
      const k = t.c; commodity[k] = commodity[k] || { trucks: 0, tonnes: 0, tat: [] };
      commodity[k].trucks++; commodity[k].tonnes += t.qty; commodity[k].tat.push(t.dep - t.arr);
    });
    Object.keys(commodity).forEach((k) => { const x = commodity[k]; x.tatMean = x.tat.reduce((a, b) => a + b, 0) / x.tat.length; delete x.tat; });
    const arrived = { unload: 0, load: 0, weigh: 0 }; Object.values(trucks).forEach((t) => { arrived[t.act]++; });
    const departed = { unload: 0, load: 0, weigh: 0 }; done.forEach((t) => { departed[t.act]++; });
    let inHoppers = 0; hoppers.forEach((h) => { inHoppers += h.level; });
    let binClosing = 0; const binInv = {};
    cfg.equipment.filter((e) => e.type === 'bin').forEach((e) => { binClosing += S[e.id].inv; binInv[e.id] = { inv: S[e.id].inv, c: S[e.id].invC }; });
    const lotDelay = stats(lotsDone.filter((l) => l.truck).map((l) => l.stored - l.t));
    return {
      engine: VERSION, seed, demandFactor: df, events, endTime: now,
      trucks: { arrived, departed, rejected: rejected.length, unfinished: present.size,
        unfinishedByAct: [...present].reduce((a, id) => { const t = trucks[id]; a[t.act] = (a[t.act] || 0) + 1; return a; }, {}),
        unfinishedAt: [...present].reduce((a, id) => { const t = trucks[id]; const k = t.cur || 'arrival'; a[k] = (a[k] || 0) + 1; return a; }, {}) },
      tat, wbio, waits, waitsByAct, queues, util, blocked, changeovers, tons, commodity, hourly,
      grain: { opening, received, stored, dispatched, inHoppers, binClosing, closing: binClosing + inHoppers, balanceError: balErr, lotToStorage: lotDelay },
      binInv, transfers: transfersLog, violations: diag, trace: traceOn ? trace : undefined,
      records: opt.records ? Object.values(trucks).map((t) => ({ id: t.id, act: t.act, c: t.c, qty: t.qty, arr: t.arr, wbIn: t.wbIn, wbOut: t.wbOut, dep: t.dep, rejected: rejected.includes(t) })) : undefined
    };
  }

  // ---------- experiments ----------
  const T95 = [12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228, 2.201, 2.179, 2.160, 2.145, 2.131, 2.120, 2.110, 2.101, 2.093, 2.086, 2.080, 2.074, 2.069, 2.064, 2.060, 2.056, 2.052, 2.048, 2.045, 2.042];
  function tcrit(n) { return n < 2 ? NaN : (n - 1 <= T95.length ? T95[n - 2] : 1.96); }
  function ci(xs) {
    const v = xs.filter((x) => x != null && isFinite(x)); const n = v.length;
    if (!n) return { n: 0, mean: null, hw: null, sd: null, min: null, max: null };
    const m = v.reduce((a, b) => a + b, 0) / n;
    const sd = n > 1 ? Math.sqrt(v.reduce((a, b) => a + (b - m) * (b - m), 0) / (n - 1)) : 0;
    return { n, mean: m, sd, hw: n > 1 ? tcrit(n) * sd / Math.sqrt(n) : null, min: Math.min(...v), max: Math.max(...v) };
  }
  const KPI = {
    tatUnload: { label: 'Unloading turnaround', unit: 'min', get: (r) => r.tat.unload.mean, better: -1 },
    tatUnloadP90: { label: 'Unloading turnaround, 90th percentile', unit: 'min', get: (r) => r.tat.unload.p90, better: -1 },
    tatLoad: { label: 'Loading turnaround', unit: 'min', get: (r) => r.tat.load.mean, better: -1 },
    tatWeigh: { label: 'Weighbridge-only turnaround', unit: 'min', get: (r) => r.tat.weigh.mean, better: -1 },
    wbio: { label: 'Weigh-in to weigh-out (ERP)', unit: 'min', get: (r) => r.wbio.mean, better: -1 },
    unloadTrucks: { label: 'Unloading trucks completed', unit: 'trucks', get: (r) => r.trucks.departed.unload, better: 1 },
    trucks: { label: 'Trucks completed', unit: 'trucks', get: (r) => r.trucks.departed.unload + r.trucks.departed.load + r.trucks.departed.weigh, better: 1 },
    received: { label: 'Grain received', unit: 't', get: (r) => r.grain.received, better: 1 },
    stored: { label: 'Grain into storage', unit: 't', get: (r) => r.grain.stored, better: 1 },
    dispatched: { label: 'Grain dispatched', unit: 't', get: (r) => r.grain.dispatched, better: 1 },
    unfinished: { label: 'Trucks still on site at close', unit: 'trucks', get: (r) => r.trucks.unfinished, better: -1 },
    tipQueueMax: { label: 'Longest queue for a hopper', unit: 'trucks', get: (r) => r.queues.tip.max, better: -1 }
  };
  function runExperiment(cfg, opt) {
    opt = opt || {};
    const reps = opt.reps || 10; const base = opt.seed || 20261019;
    const v = validate(cfg); if (!v.ok) throw new Error(v.errors[0].msg);
    const out = [];
    for (let i = 0; i < reps; i++) {
      out.push(runReplication(cfg, { seed: hash(base, i), demandFactor: opt.demandFactor, warmup: opt.warmup, validation: v, trace: opt.trace && i === 0 }));
      if (opt.onProgress) opt.onProgress(i + 1, reps);
    }
    return { reps: out, summary: summarize(out), validation: { errors: v.errors.length, warnings: v.warnings.length } };
  }
  function summarize(reps) {
    const s = {};
    Object.keys(KPI).forEach((k) => { s[k] = ci(reps.map(KPI[k].get)); });
    const util = {}; Object.keys(reps[0].util).forEach((id) => { util[id] = ci(reps.map((r) => r.util[id])); });
    const waits = {}; Object.keys(reps[0].waits).forEach((k) => { waits[k] = ci(reps.map((r) => r.waits[k])); });
    const queues = {}; Object.keys(reps[0].queues).forEach((k) => { queues[k] = { avg: ci(reps.map((r) => r.queues[k].avg)), max: ci(reps.map((r) => r.queues[k].max)) }; });
    const blocked = {}; Object.keys(reps[0].blocked).forEach((k) => { blocked[k] = ci(reps.map((r) => r.blocked[k])); });
    const violations = reps.reduce((a, r) => a + r.violations.length, 0);
    const maxBal = Math.max(...reps.map((r) => Math.abs(r.grain.balanceError)));
    return { kpi: s, util, waits, queues, blocked, violations, maxBalanceError: maxBal, n: reps.length };
  }
  function paired(a, b, key) {
    const g = KPI[key].get; const d = [];
    for (let i = 0; i < Math.min(a.length, b.length); i++) { const x = g(a[i]), y = g(b[i]); if (x != null && y != null) d.push(y - x); }
    const c = ci(d); c.significant = c.hw != null && Math.abs(c.mean) > c.hw; return c;
  }

  // ---------- scenarios ----------
  function applyScenario(cfg, ops) {
    const c = clone(cfg);
    (ops || []).forEach((o) => {
      if (o.op === 'add') {
        c.equipment.push(clone(o.item));
        (o.edgesIn || []).forEach((a) => c.edges.push([a, o.item.id]));
        (o.edgesOut || []).forEach((b) => c.edges.push([o.item.id, b]));
      } else if (o.op === 'set') {
        const e = c.equipment.find((x) => x.id === o.id); if (e) e[o.field] = o.value;
      } else if (o.op === 'policy') { c.policies = Object.assign({}, c.policies, { [o.key]: o.value }); }
      else if (o.op === 'hours') { c.hours = Object.assign({}, c.hours, o.value); }
      else if (o.op === 'connect') { if (!c.edges.some(([x, y]) => x === o.from && y === o.to)) c.edges.push([o.from, o.to]); }
      else if (o.op === 'disconnect') { c.edges = c.edges.filter(([x, y]) => !(x === o.from && y === o.to)); }
      else if (o.op === 'profile') { c.demand[o.act].profile = o.value.slice(); }
    });
    return c;
  }
  function nextId(cfg, prefix) { let i = 1; while (cfg.equipment.some((e) => e.id === prefix + i)) i++; return prefix + i; }

  // constraint finder: add capacity to each candidate and measure the paired effect
  function constraintCandidates(cfg) {
    const v = validate(cfg); const out = [];
    const grp = (t, label) => { const es = cfg.equipment.filter((e) => e.type === t); if (!es.length) return;
      const e0 = es[0]; out.push({ key: t, label: 'One more ' + label, ids: es.map((e) => e.id), ops: [{ op: 'set', id: e0.id, field: 'cap', value: (e0.cap || 1) + 1 }] }); };
    grp('weighbridge', 'weighbridge lane'); grp('sampler', 'sampling lane'); grp('grader', 'grading station');
    const hs = cfg.equipment.filter((e) => e.type === 'hopper');
    if (hs.length) {
      const h0 = hs[0]; const id = nextId(cfg, 'HX');
      out.push({ key: 'hopper', label: 'One more hopper beside ' + h0.name, ids: hs.map((h) => h.id),
        ops: [{ op: 'add', item: Object.assign(clone(h0), { id, name: 'Extra hopper', level0: 0 }), edgesOut: cfg.edges.filter(([a]) => a === h0.id).map(([, b]) => b) }] });
    }
    Object.keys(v.users).forEach((m) => {
      const e = cfg.equipment.find((x) => x.id === m);
      out.push({ key: m, label: e.name + ' at +50% rate', ids: [m], ops: [{ op: 'set', id: m, field: 'rate', value: Math.round(e.rate * 1.5) }] });
    });
    return out;
  }

  // ---------- sample facilities (illustrative values, not customer data) ----------
  const PROFILE = [0, 0, 0, 0, 0, 0, 2, 4, 5, 6, 6, 6, 7, 9, 12, 13, 12, 8, 0, 0, 0, 0, 0, 0];
  function siteA() {
    return {
      id: 'site-a', name: 'Kareepan Silo', customer: 'Demo Agri', version: 1, region: 'North West',
      hours: { open: 6, close: 18, overtime: 4 },
      commodities: [{ id: 'YM', name: 'Yellow maize', color: '#d4a017' }, { id: 'WM', name: 'White maize', color: '#c9c2a8' }, { id: 'SB', name: 'Soybeans', color: '#8a9a3b' }],
      equipment: [
        { id: 'S1', type: 'sampler', name: 'Sampler', cap: 1, time: [1.5, 2.5, 4] },
        { id: 'G1', type: 'grader', name: 'Grading lab', cap: 2, time: [4, 6, 10], reject: 0.02 },
        { id: 'WB1', type: 'weighbridge', name: 'Weighbridge', cap: 1, time: [1.5, 2, 3], moves: 'both' },
        { id: 'H1', type: 'hopper', name: 'Hopper 1', capT: 60, rate: 400, tip: [4, 6, 9], commodities: ['YM', 'WM'] },
        { id: 'H2', type: 'hopper', name: 'Hopper 2', capT: 60, rate: 400, tip: [4, 6, 9], commodities: ['YM', 'WM', 'SB'] },
        { id: 'C1', type: 'conveyor', name: 'Pit conveyor 1', rate: 300, changeover: 6 },
        { id: 'C2', type: 'conveyor', name: 'Pit conveyor 2', rate: 300, changeover: 6 },
        { id: 'E1', type: 'elevator', name: 'Elevator 1', rate: 200, changeover: 8 },
        { id: 'C3', type: 'conveyor', name: 'Top conveyor', rate: 300, changeover: 6 },
        { id: 'B1', type: 'bin', name: 'Bin 1', capT: 4000, commodities: ['YM'], inv: 1800, invCommodity: 'YM' },
        { id: 'B2', type: 'bin', name: 'Bin 2', capT: 4000, commodities: ['YM', 'WM'], inv: 0 },
        { id: 'B3', type: 'bin', name: 'Bin 3', capT: 4000, commodities: ['WM'], inv: 900, invCommodity: 'WM' },
        { id: 'B4', type: 'bin', name: 'Bin 4', capT: 2500, commodities: ['SB'], inv: 400, invCommodity: 'SB' },
        { id: 'R1', type: 'conveyor', name: 'Reclaim conveyor', rate: 250, changeover: 6 },
        { id: 'L1', type: 'loadpoint', name: 'Load-out', rate: 250, setup: [3, 5, 8] }
      ],
      edges: [['H1', 'C1'], ['H2', 'C2'], ['C1', 'E1'], ['C2', 'E1'], ['E1', 'C3'], ['C3', 'B1'], ['C3', 'B2'], ['C3', 'B3'], ['C3', 'B4'],
        ['B1', 'R1'], ['B2', 'R1'], ['B3', 'R1'], ['B4', 'R1'], ['R1', 'E1'], ['E1', 'L1']],
      sequences: { unload: ['sample', 'grade', 'weigh_in', 'tip', 'weigh_out'], load: ['weigh_in', 'load', 'weigh_out'], weigh: ['weigh_in'] },
      demand: {
        unload: { daily: 62, profile: PROFILE.slice(), payload: [24, 32.5, 38], mix: { YM: 0.6, WM: 0.3, SB: 0.1 } },
        load: { daily: 8, profile: [0, 0, 0, 0, 0, 0, 3, 5, 6, 6, 5, 4, 3, 3, 2, 2, 1, 1, 0, 0, 0, 0, 0, 0], payload: [30, 34, 36], mix: { YM: 1 } },
        weigh: { daily: 5, profile: new Array(24).fill(1) }
      },
      policies: { tip: 'feasible', weigh: 'fifo', transfer: 'fifo' },
      initial: { queue: { unload: 6, load: 0, weigh: 0 } }
    };
  }
  function siteB() {
    return {
      id: 'site-b', name: 'Rietvlei Depot', customer: 'Demo Agri', version: 1, region: 'Free State',
      hours: { open: 6, close: 18, overtime: 4 },
      commodities: [{ id: 'YM', name: 'Yellow maize', color: '#d4a017' }, { id: 'WM', name: 'White maize', color: '#c9c2a8' }, { id: 'SB', name: 'Soybeans', color: '#8a9a3b' }, { id: 'SF', name: 'Sunflower', color: '#5b5f6b' }],
      equipment: [
        { id: 'S1', type: 'sampler', name: 'Sampling bay', cap: 2, time: [1.5, 2.5, 4] },
        { id: 'G1', type: 'grader', name: 'Grading lab', cap: 3, time: [4, 6, 10], reject: 0.02 },
        { id: 'WB1', type: 'weighbridge', name: 'Weighbridge in', cap: 1, time: [1.5, 2, 3], moves: 'in' },
        { id: 'WB2', type: 'weighbridge', name: 'Weighbridge out', cap: 1, time: [1.5, 2, 3], moves: 'out' },
        { id: 'H1', type: 'hopper', name: 'Hopper 1', capT: 60, rate: 400, tip: [4, 6, 9], commodities: ['YM', 'WM'] },
        { id: 'H2', type: 'hopper', name: 'Hopper 2', capT: 60, rate: 400, tip: [4, 6, 9], commodities: ['YM', 'WM'] },
        { id: 'H3', type: 'hopper', name: 'Hopper 3', capT: 60, rate: 400, tip: [4, 6, 9], commodities: ['YM', 'SB', 'SF'] },
        { id: 'H4', type: 'hopper', name: 'Hopper 4', capT: 60, rate: 400, tip: [4, 6, 9], commodities: ['SB', 'SF'] },
        { id: 'C1', type: 'conveyor', name: 'Pit conveyor A', rate: 300, changeover: 6 },
        { id: 'E1', type: 'elevator', name: 'Elevator A', rate: 240, changeover: 8 },
        { id: 'C3', type: 'conveyor', name: 'Top conveyor A', rate: 300, changeover: 6 },
        { id: 'C2', type: 'conveyor', name: 'Pit conveyor B', rate: 300, changeover: 6 },
        { id: 'E2', type: 'elevator', name: 'Elevator B', rate: 180, changeover: 8 },
        { id: 'C4', type: 'conveyor', name: 'Top conveyor B', rate: 300, changeover: 6 },
        { id: 'B1', type: 'bin', name: 'Bin A1', capT: 5000, commodities: ['YM'], inv: 2200, invCommodity: 'YM' },
        { id: 'B2', type: 'bin', name: 'Bin A2', capT: 5000, commodities: ['YM', 'WM'], inv: 0 },
        { id: 'B3', type: 'bin', name: 'Bin A3', capT: 5000, commodities: ['WM'], inv: 1500, invCommodity: 'WM' },
        { id: 'B4', type: 'bin', name: 'Bin B1', capT: 3000, commodities: ['SB'], inv: 600, invCommodity: 'SB' },
        { id: 'B5', type: 'bin', name: 'Bin B2', capT: 3000, commodities: ['SF'], inv: 300, invCommodity: 'SF' },
        { id: 'B6', type: 'bin', name: 'Bin B3', capT: 3000, commodities: ['YM', 'SB'], inv: 0 },
        { id: 'R1', type: 'conveyor', name: 'Reclaim A', rate: 300, changeover: 6 },
        { id: 'R2', type: 'conveyor', name: 'Reclaim B', rate: 300, changeover: 6 },
        { id: 'L1', type: 'loadpoint', name: 'Load-out', rate: 250, setup: [3, 5, 8] }
      ],
      edges: [['H1', 'C1'], ['H2', 'C1'], ['C1', 'E1'], ['E1', 'C3'], ['C3', 'B1'], ['C3', 'B2'], ['C3', 'B3'],
        ['H3', 'C2'], ['H4', 'C2'], ['C2', 'E2'], ['E2', 'C4'], ['C4', 'B4'], ['C4', 'B5'], ['C4', 'B6'],
        ['B1', 'R1'], ['B2', 'R1'], ['B3', 'R1'], ['R1', 'L1'], ['B4', 'R2'], ['B5', 'R2'], ['B6', 'R2'], ['R2', 'L1']],
      sequences: { unload: ['sample', 'grade', 'weigh_in', 'tip', 'weigh_out'], load: ['weigh_in', 'load', 'weigh_out'], weigh: ['weigh_in'] },
      demand: {
        unload: { daily: 115, profile: PROFILE.slice(), payload: [24, 32.5, 38], mix: { YM: 0.5, WM: 0.2, SB: 0.2, SF: 0.1 } },
        load: { daily: 12, profile: [0, 0, 0, 0, 0, 0, 3, 5, 6, 6, 5, 4, 3, 3, 2, 2, 1, 1, 0, 0, 0, 0, 0, 0], payload: [30, 34, 36], mix: { YM: 0.7, SB: 0.3 } },
        weigh: { daily: 8, profile: new Array(24).fill(1) }
      },
      policies: { tip: 'feasible', weigh: 'fifo', transfer: 'fifo' },
      initial: { queue: { unload: 4, load: 0, weigh: 0 } }
    };
  }

  // ---------- acceptance and regression tests ----------
  function selfTests() {
    const results = [];
    const T = (name, fn) => { try { const d = fn(); results.push({ name, pass: d.pass, detail: d.detail }); } catch (e) { results.push({ name, pass: false, detail: 'Error: ' + e.message }); } };
    const noViol = (rs) => rs.reduce((a, r) => a + r.violations.length, 0);
    T('Test 1: two different layouts run from configuration only', () => {
      const a = runExperiment(siteA(), { reps: 3 }), b = runExperiment(siteB(), { reps: 3 });
      const va = noViol(a.reps), vb = noViol(b.reps);
      return { pass: va === 0 && vb === 0 && a.reps[0].trucks.departed.unload > 0 && b.reps[0].trucks.departed.unload > 0,
        detail: '2-hopper shared-elevator site and 4-hopper two-route site both ran; rule failures: ' + (va + vb) + '.' };
    });
    T('Test 2: changed hopper-to-bin reach is respected', () => {
      const c = siteB(); c.edges = c.edges.filter(([x, y]) => !(x === 'C4' && y === 'B6')); c.edges.push(['C4', 'B6']);
      // H3 must never reach Bin A1 (different route); then cut C4 > B4 and check no flow to B4
      const c2 = applyScenario(c, [{ op: 'disconnect', from: 'C4', to: 'B4' }, { op: 'connect', from: 'C3', to: 'B4' }, { op: 'connect', from: 'H4', to: 'C1' }]);
      c2.equipment.find((e) => e.id === 'H1').commodities = ['YM', 'WM'];
      const v = validate(c2);
      const r = runReplication(c2, { seed: 7, validation: v });
      const bad = Object.keys(r.transfers).filter((k) => k === 'H3>B4');
      return { pass: v.ok && bad.length === 0 && r.violations.length === 0, detail: 'After rerouting, Hopper 3 sent ' + (r.transfers['H3>B4'] || 0) + ' t to Bin B1 (expected 0).' };
    });
    T('Test 3: additional hopper shares the same downstream limits', () => {
      const c = siteA();
      const c2 = applyScenario(c, [{ op: 'add', item: { id: 'H3', type: 'hopper', name: 'Hopper 3', capT: 60, rate: 220, tip: [4, 6, 9], commodities: ['YM', 'WM'] }, edgesOut: ['C1'] }]);
      const r = runReplication(c2, { seed: 11 });
      return { pass: r.violations.length === 0 && r.util.H3 > 0 && r.util.E1 <= 1 + 1e-9, detail: 'Hopper 3 was used ' + (r.util.H3 * 100).toFixed(1) + '% of the day; Elevator 1 never exceeded one stream.' };
    });
    T('Test 4: incompatible commodities never share a route at once', () => {
      const c = siteA(); c.demand.unload.mix = { YM: 0.5, SB: 0.5 };
      const r = runReplication(c, { seed: 5 });
      const co = Object.values(r.changeovers).reduce((a, b) => a + b, 0);
      return { pass: r.violations.length === 0 && co > 0, detail: co + ' changeovers enforced; overlap or mixing failures: ' + r.violations.length + '.' };
    });
    T('Test 5: fractional payloads keep the material balance', () => {
      const c = siteA(); c.demand.unload.payload = [21.37, 29.91, 37.73];
      const rs = runExperiment(c, { reps: 5 }).reps;
      const m = Math.max(...rs.map((r) => Math.abs(r.grain.balanceError)));
      return { pass: m < 1e-6 && noViol(rs) === 0, detail: 'Largest balance error ' + m.toExponential(2) + ' t across 5 days.' };
    });
    T('Test 6: arrivals reproduce the hourly profile', () => {
      const c = siteA(); c.demand.unload.daily = 200; const rs = runExperiment(c, { reps: 30 }).reps;
      const prof = c.demand.unload.profile; const tot = prof.slice(6, 18).reduce((a, b) => a + b, 0);
      const sim = new Array(24).fill(0); rs.forEach((r) => r.hourly.unload.forEach((x, i) => { sim[i] += x; }));
      const n = sim.reduce((a, b) => a + b, 0);
      let worst = 0; for (let h = 6; h < 18; h++) worst = Math.max(worst, Math.abs(sim[h] / n - prof[h] / tot));
      const meanDaily = n / 30;
      return { pass: worst < 0.02 && Math.abs(meanDaily - 200) < 12, detail: 'Mean ' + meanDaily.toFixed(1) + ' arrivals per day for 200 configured; largest hourly share gap ' + (worst * 100).toFixed(2) + ' points.' };
    });
    T('Test 7: FIFO and commodity batching compared without code changes', () => {
      const a = siteA(); a.policies.tip = 'fifo'; const b = applyScenario(a, [{ op: 'policy', key: 'tip', value: 'batch' }, { op: 'policy', key: 'transfer', value: 'batch' }]);
      const ra = runReplication(a, { seed: 3 }), rb = runReplication(b, { seed: 3 });
      const ca = Object.values(ra.changeovers).reduce((x, y) => x + y, 0), cb = Object.values(rb.changeovers).reduce((x, y) => x + y, 0);
      return { pass: ra.violations.length === 0 && rb.violations.length === 0 && (ca !== cb || ra.tat.unload.mean !== rb.tat.unload.mean),
        detail: 'Changeovers FIFO ' + ca + ', batching ' + cb + '.' };
    });
    T('Test 8: concurrent activities share the weighbridge', () => {
      const c = siteA(); const r = runReplication(c, { seed: 9 });
      const d = r.trucks.departed;
      return { pass: d.unload > 0 && d.load > 0 && d.weigh > 0 && r.util.WB1 <= 1 + 1e-9 && r.violations.length === 0,
        detail: 'Departed: ' + d.unload + ' unloading, ' + d.load + ' loading, ' + d.weigh + ' weighbridge-only; weighbridge busy ' + (r.util.WB1 * 100).toFixed(0) + '%.' };
    });
    T('Reproducibility: same seed gives identical results', () => {
      const c = siteB(); const a = JSON.stringify(runReplication(c, { seed: 42 })), b = JSON.stringify(runReplication(c, { seed: 42 })), d = JSON.stringify(runReplication(c, { seed: 43 }));
      return { pass: a === b && a !== d, detail: 'Seed 42 run twice matched; seed 43 differed.' };
    });
    T('Invalid layout is blocked with a plain explanation', () => {
      const c = siteA(); c.edges = c.edges.filter(([x, y]) => !(x === 'C3' && y === 'B4'));
      const v = validate(c);
      const m = v.errors.find((e) => /Hopper 2 cannot deliver Soybeans/.test(e.msg));
      let threw = false; try { runReplication(c, { seed: 1 }); } catch (e) { threw = true; }
      return { pass: !!m && threw, detail: m ? m.msg : 'No message produced.' };
    });
    T('Opening backlog and stock are loaded', () => {
      const c = siteA(); c.initial.queue.unload = 15; const r = runReplication(c, { seed: 2 });
      return { pass: r.grain.opening === 3100 && r.trucks.arrived.unload >= 15, detail: 'Opening stock ' + r.grain.opening + ' t; ' + r.trucks.arrived.unload + ' unloading trucks including 15 waiting at the gate.' };
    });
    T('Sample results match their own trucks', () => {
      const c = siteB(); c.equipment.find((e) => e.id === 'G1').time = [1, 6, 25];
      const rs = runExperiment(c, { reps: 3 }).reps;
      const sm = rs.reduce((a, r) => a + r.violations.filter((x) => x.rule === 'sample-match').length, 0);
      return { pass: sm === 0, detail: 'Highly variable grading times reorder samples; mismatches: ' + sm + '.' };
    });
    return results;
  }

  const api = { VERSION, TYPES, CONNECT, STEP_LABEL, ACT_LABEL, KPI, validate, buildRoutes, runReplication, runExperiment, summarize, paired, ci,
    applyScenario, constraintCandidates, nextId, samples: { siteA, siteB }, selfTests, hash, clone };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.SiloEngine = api;
})(typeof self !== 'undefined' ? self : this);

