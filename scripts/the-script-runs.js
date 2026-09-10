// Does the console's script get to the end of itself?
//
// `node --check` parses. A file that parses can still stop dead on its first line of *execution* —
// a `const` read before its declaration, a helper called before it exists — and the page then looks
// exactly the way it looks after a syntax error: everything renders, nothing works, and no Python
// test can see it. That failure was one line away from shipping (a listener wired to `canvas`
// three hundred lines above where `canvas` is declared), and `node --check` was green on it.
//
// So: a document thin enough to fit on a screen, and the file is required. Nothing here pretends to
// be a browser and nothing asserts about behaviour — the only question is whether the file reaches
// its last line. Every element asked for exists, because a stub that answered `null` would be
// testing this program's handling of a missing element rather than the order it does things in.
const nothing = () => {};
const none = [];
const make = () =>
  new Proxy(
    {},
    {
      get(target, name) {
        if (name in target) return target[name];
        if (typeof name === 'symbol') return undefined;
        if (name === 'then') return undefined;
        if (name === 'classList')
          return { add: nothing, remove: nothing, toggle: nothing, contains: () => false };
        if (name === 'dataset' || name === 'style') return {};
        if (name === 'querySelectorAll') return () => none;
        if (name === 'querySelector') return () => make();
        if (name === 'closest') return () => null;
        if (name === 'getBoundingClientRect')
          return () => ({ top: 0, left: 0, right: 0, bottom: 0, width: 0, height: 0 });
        if (name === 'textContent' || name === 'value' || name === 'innerHTML') return '';
        if (name === 'hidden' || name === 'checked' || name === 'disabled') return false;
        if (name === 'children' || name === 'files') return none;
        if (name === 'parentElement' || name === 'firstElementChild') return null;
        return nothing;
      },
      set() {
        return true;
      },
    }
  );

globalThis.document = new Proxy(make(), {
  get(target, name) {
    if (name === 'getElementById' || name === 'querySelector') return () => make();
    if (name === 'querySelectorAll') return () => none;
    if (name === 'createElement' || name === 'createElementNS') return () => make();
    if (name === 'createDocumentFragment') return () => make();
    if (name === 'body' || name === 'documentElement' || name === 'head') return make();
    if (name === 'hidden') return false;
    if (name === 'title') return '';
    if (name === 'visibilityState') return 'visible';
    if (name === 'readyState') return 'complete';
    return Reflect.get(target, name);
  },
  set() {
    return true;
  },
});
globalThis.window = globalThis;
globalThis.self = globalThis;
globalThis.location = { href: 'http://127.0.0.1:8787/', pathname: '/', search: '', hash: '' };
globalThis.localStorage = { getItem: () => null, setItem: nothing, removeItem: nothing };
globalThis.sessionStorage = globalThis.localStorage;
globalThis.addEventListener = nothing;
globalThis.removeEventListener = nothing;
globalThis.matchMedia = () => ({ matches: false, addEventListener: nothing, addListener: nothing });
globalThis.getComputedStyle = () => ({ getPropertyValue: () => '' });
globalThis.requestAnimationFrame = nothing;
globalThis.cancelAnimationFrame = nothing;
// Timers are stubbed rather than left alone for two reasons: a scheduled callback would run this
// file's periodic work against a document that is not one, and a pending timer keeps node alive
// long after the only question here has been answered.
globalThis.setTimeout = () => 0;
globalThis.setInterval = () => 0;
globalThis.clearTimeout = nothing;
globalThis.clearInterval = nothing;
globalThis.EventSource = function () {
  return make();
};
globalThis.ResizeObserver = function () {
  return { observe: nothing, unobserve: nothing, disconnect: nothing };
};
globalThis.MutationObserver = globalThis.ResizeObserver;
globalThis.fetch = () =>
  Promise.resolve({ ok: true, status: 200, text: () => Promise.resolve(''), json: () => Promise.resolve({}) });
globalThis.htmx = { process: nothing, ajax: nothing, on: nothing, config: {} };
globalThis.navigator = { clipboard: { writeText: () => Promise.resolve() }, userAgent: 'node' };
globalThis.CSS = { escape: (one) => String(one) };
globalThis.alert = nothing;
globalThis.confirm = () => false;
globalThis.prompt = () => null;
globalThis.scrollTo = nothing;

require(process.argv[2]);
console.log('console.js runs to the end.');
process.exit(0);
