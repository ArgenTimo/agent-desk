/* The console's browser half, and all of it.
 *
 * Four jobs, none of which needs a framework: keep the page in step with the server, switch
 * between chats, carry a card into the middle when somebody drags one there, and say plainly when
 * the connection has gone quiet. Everything else is server-rendered — htmx, when it is present,
 * only removes the page reload (docs/adr/0003).
 */

const poll = window.POLL_SECONDS || 2;
const asof = document.getElementById('asof');
const state = document.getElementById('stream-state');
const pins = document.getElementById('pins');
let lastChecked = 0;

if (!window.htmx) document.getElementById('no-htmx').hidden = false;

/* --- posting without htmx ---------------------------------------------------------------------- */
// htmx is vendored, not fetched, so it is sometimes not there — and the two things this page does
// constantly are a form post and a swap. Without this, asking a question navigates away and comes
// back, which is a page reload in the middle of the one interaction that is supposed to cost
// nothing (docs/04-threads-and-blocks.md). With htmx present this does nothing at all: htmx has
// already handled the submit, and two posts would ask the same question twice.
document.addEventListener('submit', async (event) => {
  const form = event.target;
  if (window.htmx || !form.hasAttribute('hx-post')) return;
  const selector = form.getAttribute('hx-target');
  const into = selector === 'closest .tabs' ? form.closest('.tabs') : document.querySelector(selector);
  if (!into) return;

  event.preventDefault();
  const body = new URLSearchParams(new FormData(form));
  form.reset();
  let response;
  try {
    response = await fetch(form.action, {
      method: 'POST',
      headers: { 'HX-Request': 'true' },
      body,
    });
  } catch {
    return;
  }
  if (!response.ok) return;
  const wasTabs = into.classList.contains('tabs');
  const html = await response.text();
  if (form.getAttribute('hx-swap') === 'outerHTML') into.outerHTML = html;
  else into.innerHTML = html;
  swapped(wasTabs);
});

/* --- the width of the columns ------------------------------------------------------------------ */
// How much of the screen the middle deserves depends on the screen and on what is being read, so
// it is not a decision this file gets to make once. Drag a handle to set it, double-click to put
// it back, and the browser remembers per machine — this is a local tool, and the width is a
// preference, not data.
const grid = document.querySelector('.desk-grid');
const WIDTHS = 'agent-desk:widths';

function setWidths(left, right) {
  const most = Math.max(240, innerWidth * 0.4);
  if (left !== null) grid.style.setProperty('--left', `${Math.min(Math.max(left, 180), most)}px`);
  if (right !== null) grid.style.setProperty('--right', `${Math.min(Math.max(right, 160), most)}px`);
}

try {
  const saved = JSON.parse(localStorage.getItem(WIDTHS) || 'null');
  if (saved) setWidths(saved.left, saved.right);
  if (saved?.blockers) grid.style.setProperty('--blockers', saved.blockers);
} catch {
  // A browser with storage switched off gets the defaults, which are fine.
}

function remember() {
  try {
    localStorage.setItem(
      WIDTHS,
      JSON.stringify({
        left: parseFloat(getComputedStyle(grid).getPropertyValue('--left')),
        right: parseFloat(getComputedStyle(grid).getPropertyValue('--right')),
        blockers: getComputedStyle(grid).getPropertyValue('--blockers').trim(),
      })
    );
  } catch {
    // Nothing to do: the widths still work for this window.
  }
}

for (const handle of document.querySelectorAll('.gutter')) {
  const side = handle.dataset.gutter;

  handle.addEventListener('pointerdown', (event) => {
    event.preventDefault();
    handle.setPointerCapture(event.pointerId);
    handle.classList.add('pulling');
    document.body.classList.add(side === 'split' ? 'pulling-across' : 'pulling');
    const startX = event.clientX;
    const startY = event.clientY;
    const column = grid.querySelector('.col-right');
    const startSplit = document.querySelector('.blockers')?.getBoundingClientRect().height || 0;
    const startLeft = grid.querySelector('.col-left').getBoundingClientRect().width;
    const startRight = grid.querySelector('.col-right').getBoundingClientRect().width;

    const move = (moved) => {
      if (side === 'split') {
        const tall = column?.getBoundingClientRect().height || 1;
        const share = ((startSplit + moved.clientY - startY) / tall) * 100;
        grid.style.setProperty('--blockers', `${Math.min(Math.max(share, 10), 85)}%`);
        return;
      }
      const dx = moved.clientX - startX;
      if (side === 'left') setWidths(startLeft + dx, null);
      else setWidths(null, startRight - dx);
    };
    const done = () => {
      handle.removeEventListener('pointermove', move);
      handle.classList.remove('pulling');
      document.body.classList.remove('pulling', 'pulling-across');
      remember();
    };
    handle.addEventListener('pointermove', move);
    handle.addEventListener('pointerup', done, { once: true });
    handle.addEventListener('pointercancel', done, { once: true });
  });

  // The keyboard reaches this too: it is a control, and a control only a mouse can use is one
  // half of the window somebody cannot arrange.
  handle.addEventListener('keydown', (event) => {
    const step = event.shiftKey ? 48 : 16;
    const left = grid.querySelector('.col-left').getBoundingClientRect().width;
    const right = grid.querySelector('.col-right').getBoundingClientRect().width;
    if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
      event.preventDefault();
      const dx = event.key === 'ArrowRight' ? step : -step;
      if (side === 'left') setWidths(left + dx, null);
      else setWidths(null, right - dx);
      remember();
    }
  });

  handle.addEventListener('dblclick', () => {
    grid.style.removeProperty('--left');
    grid.style.removeProperty('--right');
    grid.style.removeProperty('--blockers');
    try {
      localStorage.removeItem(WIDTHS);
    } catch {
      // Same as above.
    }
  });
}

/* --- what is showing, and how big ---------------------------------------------------------------- */
// Five areas with names — overview, workbench, input, blockers, idea pool (docs/06-console.md) —
// and any of them can be put away. What somebody wants on the screen at four in the afternoon is
// not what they wanted at ten, so this is a preference and lives in this browser beside the
// widths and the order of the chats.
const PANES = 'agent-desk:panes';
let away = new Set();

try {
  away = new Set(JSON.parse(localStorage.getItem(PANES) || '[]'));
} catch {
  // Everything shows, which is the default anyway.
}

function applyPanes() {
  for (const pane of document.querySelectorAll('[data-pane]')) {
    pane.hidden = away.has(pane.dataset.pane);
  }
  for (const rail of document.querySelectorAll('.rail[data-show]')) {
    rail.hidden = !away.has(rail.dataset.show);
  }
  // The gutter beside a hidden column has nothing left to drag.
  const left = document.querySelector('.gutter[data-gutter="left"]');
  const right = document.querySelector('.gutter[data-gutter="right"]');
  if (left) left.hidden = away.has('overview');
  if (right) right.hidden = away.has('right');
  // Inside the right column: the blockers, the split handle, and the pool.
  const blockers = document.querySelector('.blockers');
  const split = document.querySelector('.gutter[data-gutter="split"]');
  const pool = document.getElementById('idea-list');
  const poolHead = document.querySelector('.col-head.second');
  const blockersHead = document.querySelector('.col-right .col-head:not(.second)');
  if (blockers) blockers.hidden = away.has('blockers');
  if (blockersHead) blockersHead.classList.toggle('folded', away.has('blockers'));
  if (pool) pool.hidden = away.has('pool');
  if (poolHead) poolHead.classList.toggle('folded', away.has('pool'));
  if (split) split.hidden = away.has('blockers') || away.has('pool');
}

function rememberPanes() {
  try {
    localStorage.setItem(PANES, JSON.stringify([...away]));
  } catch {
    // It still holds for this window.
  }
}

document.addEventListener('click', (event) => {
  const hide = event.target.closest('.pane-hide');
  const show = event.target.closest('.rail[data-show]');
  const head = event.target.closest('.col-head.folded');
  if (hide) away.add(hide.dataset.hide);
  else if (show) away.delete(show.dataset.show);
  else if (head) {
    // A folded half is brought back by its own heading, which is the only part of it still there.
    away.delete(head.classList.contains('second') ? 'pool' : 'blockers');
  } else return;
  applyPanes();
  rememberPanes();
});

applyPanes();

/* --- the menu on a project card ----------------------------------------------------------------- */
// The `⋯` is a menu, not a place. Without this script it is a link to the project's own page,
// which has everything the menu offers; with it, the options open where the card is.
document.addEventListener('click', (event) => {
  const opener = event.target.closest('.more[data-menu]');
  const open = document.querySelector('.menu:not([hidden])');
  if (open && (!opener || open.id !== opener.dataset.menu)) open.hidden = true;
  if (!opener) return;

  const menu = document.getElementById(opener.dataset.menu);
  if (!menu) return; // The link still works: it goes to the page.
  event.preventDefault();
  menu.hidden = !menu.hidden;
});

// A menu that outlived the card it belonged to is a menu floating over somebody else's project.
document.addEventListener('keydown', (event) => {
  if (event.key !== 'Escape') return;
  const open = document.querySelector('.menu:not([hidden])');
  if (open) open.hidden = true;
});

/* --- what is folded shut ----------------------------------------------------------------------- */
// The board is re-rendered from the server whenever it changes, and the server has no idea which
// cards somebody folded shut — so without this, closing one and waiting two seconds opened it
// again. Which cards are folded is a preference about this window, so it lives in this browser
// beside the column widths and the order of the chats.
const FOLDED = 'agent-desk:folded';
let folded = new Set();

try {
  folded = new Set(JSON.parse(localStorage.getItem(FOLDED) || '[]'));
} catch {
  // A browser with storage switched off gets every card open, which is the default anyway.
}

function cardKey(card) {
  return `${card.dataset.kind}:${card.dataset.id}`;
}

function applyFolded() {
  for (const card of document.querySelectorAll('#board details[data-kind]')) {
    card.open = !folded.has(cardKey(card));
  }
}

// `toggle` does not bubble, so it is caught on the way down.
document.addEventListener(
  'toggle',
  (event) => {
    const card = event.target;
    if (!card.dataset?.kind || !card.closest('#board')) return;
    if (card.open) folded.delete(cardKey(card));
    else folded.add(cardKey(card));
    try {
      localStorage.setItem(FOLDED, JSON.stringify([...folded]));
    } catch {
      // It still holds for this window.
    }
  },
  true
);

/* --- the stream ------------------------------------------------------------------------------ */
function checked() {
  lastChecked = Date.now();
  asof.textContent = `checked ${new Date().toLocaleTimeString()}`;
  state.textContent = '·';
  state.className = 'tiny';
  document.body.classList.remove('stale');
}

function lost(why) {
  // The reconnect attempt and the silence timer both fire while the server is down, and each has a
  // true thing to say; alternating them once a second is a board nobody can read.
  if (document.body.classList.contains('stale')) return;
  state.textContent = why;
  state.className = 'tiny lost';
  document.body.classList.add('stale');
}

const stream = new EventSource('/events');

// The board is pushed every couple of seconds whether or not anything changed, and replacing the
// column under somebody's hand is not a cosmetic problem: a browser fires no click at all when
// mousedown and mouseup land on different elements, so every rebuild is a click that silently
// does nothing — and a drag that was in flight is cancelled outright. Two rules, both cheap: the
// same board is not rebuilt, and a board is never rebuilt mid-drag.
let lastBoard = '';
stream.addEventListener('board', (event) => {
  checked();
  if (event.data === lastBoard || document.body.classList.contains('dragging-card')) return;
  lastBoard = event.data;
  document.getElementById('board').innerHTML = event.data;
  applyFolded();
  // A session that has started its first subagent has parts it did not have a moment ago, and a
  // checkout whose last session ended has none any more.
  for (const card of surface?.querySelectorAll('.pin[data-kind]') || []) showParts(card);
  readRoom();
  // The board fragment is replaced wholesale, and the tools live inside it — under the projects,
  // where they were asked for. So the list is drawn again here rather than once at the start: a
  // push two seconds after the page opened used to leave an empty list under a heading.
  showTools();
  const waiting = document.querySelectorAll('.node.session.flagged').length;
  document.title = waiting ? `agent-desk (${waiting})` : 'agent-desk';
});
let answeredSoFar = 0;

stream.addEventListener('blocks', (event) => {
  // A ring stops turning when one more block has finished. Counted from the markup rather than
  // tracked per block: this page does not know which answer belongs to which ring, and the
  // answers arrive in the order the questions were asked.
  const settled = (event.data.match(/data-settled/g) || []).length;
  for (let i = answeredSoFar; i < settled; i += 1) ringDone();
  answeredSoFar = settled;

  // Never while somebody is reading or typing inside it: replacing the column under a selection
  // loses it, and an answer is the one thing here anybody copies out.
  if (!document.getSelection().isCollapsed) return;
  document.getElementById('blocks').innerHTML = event.data;
  if (window.htmx) htmx.process(document.getElementById('blocks'));
  syncBlocks();
  showActiveThread();
  // Only if they were already there. Yanking somebody back to the newest answer while they are
  // reading an older one is the same mistake as replacing the text under their cursor.
  checked();
});
stream.addEventListener('ideas', (event) => {
  if (document.activeElement.closest('#idea-list')) return;
  document.getElementById('idea-list').innerHTML = event.data;
  if (window.htmx) htmx.process(document.getElementById('idea-list'));
  // The column was replaced, so whatever was being looked for has to be looked for again.
  filterIdeas();
  checked();
});
stream.addEventListener('blockers', (event) => {
  // Same rule as the ideas: never replace what somebody is in the middle of pressing.
  const list = document.getElementById('blocker-list');
  if (!list || document.activeElement.closest('#blocker-list')) return;
  list.innerHTML = event.data;
  if (window.htmx) htmx.process(list);
  checked();
});
stream.addEventListener('heartbeat', checked);
stream.onerror = () => lost('stream lost — reconnecting');
setInterval(() => {
  if (lastChecked && Date.now() - lastChecked > poll * 3 * 1000) lost('no update — stream stalled');
}, 1000);

/* --- chats ----------------------------------------------------------------------------------- */
// A tab is a thread. Every block is rendered with the thread it belongs to and the page shows one
// tab's worth — which keeps the event stream stateless: the server does not need to know which tab
// each browser is looking at.
function activeThread() {
  return document.querySelector('.tab.on')?.dataset.thread || '';
}

function showActiveThread() {
  const current = activeThread();
  for (const block of document.querySelectorAll('#blocks [data-thread]')) {
    block.hidden = block.dataset.thread !== current;
  }
  const said = [...document.querySelectorAll('#blocks [data-thread]')].some((b) => !b.hidden);

  const field = document.getElementById('say-thread');
  if (field) field.value = current;
  syncBlocks();
}

document.addEventListener('click', (event) => {
  // The × is a form of its own inside the tab; let it post rather than switching to the chat
  // somebody is closing.
  if (event.target.closest('.tab-close')) return;
  const tab = event.target.closest('.tab');
  if (!tab) return;
  for (const other of document.querySelectorAll('.tab')) other.classList.toggle('on', other === tab);
  // The workbench belongs to the chat: switching to another one brings *its* surface back, and
  // `showActiveThread` puts that chat's conversation on top of it (044).
  benchOfThisChat();
  showActiveThread();
  document.getElementById('ask-text').focus();
});

// htmx swaps two fragments into this page, and both need the same thing afterwards: the tab bar,
// where the chat somebody just created has to become the one they are looking at, and the output,
// where a new message has to be visible under the field that produced it.
function swapped(isTabs) {
  if (isTabs) {
    applyTabOrder();
    // The chat somebody just created is the one they are looking at, and it is the last one.
    const tabs = [...document.querySelectorAll('.tab')];
    for (const tab of tabs) tab.classList.toggle('on', tab === tabs[tabs.length - 1]);
    // A chat that has just been created has no bench yet, so this is an empty surface either way —
    // but it is fetched like any other, so that the one path exists rather than two that agree
    // until somebody changes one of them.
    benchOfThisChat();
  }
  showActiveThread();
}

document.body.addEventListener('htmx:afterSwap', (event) => {
  swapped(!!event.target?.classList?.contains('tabs'));
  if (event.target?.id === 'idea-list' || event.target?.closest?.('#idea-list')) filterIdeas();
});

/* --- finding one thought among two hundred ------------------------------------------------------ */
// The pool could be ordered and not searched, which is the right tool for twenty ideas and the
// wrong one for two hundred.
//
// In the page rather than at the server, for two reasons that are not about speed. The column is
// replaced wholesale by the stream every time anything changes, so a filter the server applied
// would have to be a stored setting and every keystroke a round trip; and the text being searched
// is already here, in the same words somebody is looking at.
//
// A card whose *child* matches stays open, because an idea that exists only as a group of
// sub-ideas would otherwise vanish while the thing you searched for is inside it.
const findField = document.getElementById('idea-find');
const foundCount = document.getElementById('idea-found');

function filterIdeas() {
  const pool = document.getElementById('idea-list');
  if (!pool) return;
  const said = (findField?.value || '').trim().toLowerCase();
  const cards = [...pool.querySelectorAll('.idea-card')];
  if (!said) {
    for (const card of cards) card.hidden = false;
    if (foundCount) foundCount.textContent = '';
    return;
  }
  const words = said.split(/\s+/).filter(Boolean);
  const hits = new Set();
  for (const card of cards) {
    // Its own words only — `textContent` on a group would match every card under it, so a search
    // for a child's words would light up its parent and read as a hit on the wrong thought.
    const own = [
      card.dataset.label || '',
      card.querySelector(':scope > .card-head .card-name')?.title || '',
    ]
      .join(' ')
      .toLowerCase();
    if (words.every((word) => own.includes(word))) hits.add(card);
  }
  for (const card of cards) {
    // A hit, or an ancestor of one: the way to a match has to stay visible.
    const keep = hits.has(card) || [...hits].some((hit) => card.contains(hit));
    card.hidden = !keep;
    if (keep && !hits.has(card)) card.open = true;
  }
  if (foundCount) {
    foundCount.textContent = hits.size
      ? `${hits.size} of ${cards.length}`
      : 'nothing matches';
  }
}

findField?.addEventListener('input', filterIdeas);
findField?.addEventListener('keydown', (event) => {
  if (event.key !== 'Escape') return;
  event.preventDefault();
  // Once to clear what was typed, again to let go of the field — the same two-step Esc does
  // everywhere else on this page.
  if (findField.value) {
    findField.value = '';
    filterIdeas();
  } else {
    findField.blur();
  }
});

/* --- the order of the chats --------------------------------------------------------------------- */
// Tabs are dragged into the order somebody wants them in. That order is a preference rather than
// data — it says nothing about the subjects themselves — so it lives in this browser beside the
// column widths, and a machine that has never been dragged on gets them oldest first.
const TAB_ORDER = 'agent-desk:tab-order';

function rememberTabOrder() {
  try {
    localStorage.setItem(
      TAB_ORDER,
      JSON.stringify([...document.querySelectorAll('.tab')].map((tab) => tab.dataset.thread))
    );
  } catch {
    // The order still holds for this window.
  }
}

function applyTabOrder() {
  let wanted;
  try {
    wanted = JSON.parse(localStorage.getItem(TAB_ORDER) || 'null');
  } catch {
    return;
  }
  if (!Array.isArray(wanted)) return;
  const bar = document.querySelector('.tabs');
  if (!bar) return;
  const place = (tab) => {
    const at = wanted.indexOf(tab.dataset.thread);
    return at === -1 ? wanted.length : at; // A chat made since then goes to the end.
  };
  const tabs = [...bar.querySelectorAll('.tab')].sort((a, b) => place(a) - place(b));
  const adder = bar.querySelector('.tab-new');
  for (const tab of tabs) bar.insertBefore(tab, adder);
}

let draggedTab = null;

document.addEventListener('dragstart', (event) => {
  const tab = event.target.closest?.('.tab');
  if (!tab) return;
  draggedTab = tab;
  tab.classList.add('dragging');
  event.dataTransfer.effectAllowed = 'move';
  event.dataTransfer.setData('text/plain', tab.textContent.trim());
});

document.addEventListener('dragover', (event) => {
  if (!draggedTab) return;
  const over = event.target.closest?.('.tab');
  if (!over || over === draggedTab) return;
  event.preventDefault();
  const box = over.getBoundingClientRect();
  const after = event.clientX > box.left + box.width / 2;
  over.parentElement.insertBefore(draggedTab, after ? over.nextSibling : over);
});

document.addEventListener('dragend', () => {
  if (!draggedTab) return;
  draggedTab.classList.remove('dragging');
  draggedTab = null;
  rememberTabOrder();
});

/* --- carrying a card into the middle ---------------------------------------------------------- */
// Dropping a card here does two things at once, because they are the same thought: it shows what
// the card actually contains, and it says that what you type next is about that. Dragging it back
// out undoes both.
function showBenchToggle() {
  // Nothing to toggle any more: the relations are drawn between the cards themselves. Kept as the
  // one place that reacts to the bench filling and emptying.
  loadTies();
}

// What the next message is about.
//
// **A choice, when there is one, is the whole of it.** "Щёлкать мышкой по карточкам подключая их
// к контексту либо выделяя специальным инструментом, после чего мои запросы обрабатываются только
// с тем контекстом что я выбрал."
//
// Before this the bench was "everything except what you switched off", so asking about three
// cards out of thirty meant switching off twenty-seven. Choosing three and asking is the same
// gesture as choosing three and moving them — one selection, and it means the same thing wherever
// it is used, which is why this is not a mode with a switch of its own.
//
// A note is not a card the server can look up — it is text that exists only here — so it is
// carried in its own field rather than named as a target that would 404.
function pinnedTargets() {
  const chosen = chosenCards().filter(
    (pin) => pin.dataset.kind && !pin.classList.contains('own')
  );
  const carried = chosen.length
    ? chosen
    : // `.pin` matters. Without it this matched every element carrying `data-kind` *inside* a
      // card as well — the idea lines a block card lists — and a bench showing seven cards was
      // sending a hundred and twenty-three targets with every message. Silently, because the
      // count beside the field was measuring something else. The same mistake `pin()` made once
      // and for the same reason: `[data-kind]` is not a card, `.pin[data-kind]` is.
      [...pins.querySelectorAll('.pin[data-kind]:not(.own):not(.answer-card):not(.promise):not(.spent):not(.ringed):not(.put-away)')];
  return carried
    .map((pin) => `${pin.dataset.kind}:${pin.dataset.id}${pin.dataset.deep === 'yes' ? ':full' : ''}`)
    .join(',');
}

// Which earlier exchanges travel with the next message. Nothing does by default: every call is
// built from exactly what was asked for, which is what makes what it costs predictable and what
// it answered from explainable.
function attachedBlocks() {
  return [...document.querySelectorAll('#blocks .attach.on')]
    .map((button) => button.dataset.block)
    .join(',');
}

function syncTargets() {
  showBenchToggle();
  markOffEdge();
  document.getElementById('say-targets').value = pinnedTargets();
  document.getElementById('say-history').value = attachedBlocks();
  const attached = document.querySelectorAll('#blocks .attach.on').length;
  const picked = chosenCards().filter((pin) => pin.dataset.kind).length;
  // An answer card is not one of them. What it says travels with the next message already, as the
  // thread it belongs to, and `on_the_bench` drops it from the prompt for that reason — so
  // counting it here would tell somebody their message carries twice what it carries.
  const live =
    picked ||
    pins.querySelectorAll(
      '.pin:not(.answer-card):not(.promise):not(.spent):not(.ringed):not(.put-away)'
    ).length;
  const carried = live + attached;
  // Which of the two it is, said in words. "Carrying 3 cards" under a bench of thirty is a
  // sentence somebody reads twice; "asking about these 3 only" is one they read once.
  document.querySelector('.context-strip')?.classList.toggle('only-these', picked > 0);
  // And on the cards themselves. The mechanism for "only these" was already here — `pinnedTargets`
  // sends the chosen ones when there are any — but nothing on the bench showed it, so thirty cards
  // looked the same whether three of them were chosen or none were.
  for (const pin of pins.querySelectorAll('.pin[data-kind]')) {
    pin.classList.toggle('left-out', picked > 0 && !pin.classList.contains('chosen'));
  }
  const deep = pins.querySelectorAll('.pin.deep').length;
  // Built as words rather than patched afterwards: "asking about these 1 card only" is what a
  // template with a plural hole in it says, and it is the sentence somebody reads first.
  const many = live === 1 ? 'card' : `${live} cards`;
  const about = picked
    ? `asking about ${live === 1 ? 'this card' : many} only`
    : `carrying ${live === 1 ? 'one card' : many}`;
  document.getElementById('context-count').textContent = carried
    ? about +
      `${deep ? ` (${deep} in full)` : ''}` +
      `${attached ? ` and ${attached} earlier answer${attached === 1 ? '' : 's'}` : ''}`
    : '';
  document.querySelector('.context-strip').classList.toggle('on', carried > 0);
  // One idea on the workbench means one obvious next move, so the console offers it rather than
  // waiting to be told in words it already knows.
  // `.pin[...]`, not `[...]`. A block card renders every idea that message recorded, and each of
  // those lines carries `data-kind="idea"` so it can be dragged out — so this counted the lines
  // inside the conversation as well as the cards on the bench, and offered to "get started on
  // these 168" under a workbench of twenty-six. The same mistake `pin` had, in the same markup.
  const ideas = pins.querySelectorAll(
    '.pin[data-kind="idea"]:not(.spent):not(.ringed):not(.put-away)'
  ).length;
  const go = document.getElementById('get-started');
  go.hidden = ideas === 0;
  go.textContent = ideas > 1 ? `Get started on these ${ideas}` : 'Get started on it';
  // The other end of the same bar: once a chat has said what it is about there is an enquiry
  // running, and the thing anybody wants at the end of one is to keep what it arrived at.
  const asIdea = document.getElementById('as-an-idea');
  if (asIdea) asIdea.hidden = !surface?.querySelector('.pin.beginning');
  showActiveThread();
  // And write the bench down. Here rather than at each of the things that change it — taking a
  // card off, folding one, leaving one out of the message, clearing the lot — because that list
  // is already six long and the seventh would be the one nobody remembered. Anything that made
  // this console recount what is on the bench has changed the bench. The write is held back a
  // moment, so calling this eighteen times costs one request.
  rememberLayout();
}

// The attached earlier answers, let go of. Taking the *cards* off is `clearBench`, which also
// forgets where they were — emptying the list on its own left the remembered layout behind, so a
// card dropped afterwards reappeared in the place the old one had been.
function letGoOfAttached() {
  for (const button of document.querySelectorAll('#blocks .attach.on')) {
    button.classList.remove('on');
    button.textContent = 'use as context';
  }
  syncTargets();
}

// "Carry nothing" stops carrying. It used to call `clearBench`, which takes every card off the
// workbench — so a person who wanted to ask one question without the bench attached lost the bench.
// Two controls did the same destructive thing and one of them was labelled as if it were about the
// message. Taking everything off is still in the menu, where it says what it does.
document.getElementById('clear-context').addEventListener('click', () => {
  chooseNone();
  for (const pin of pins.querySelectorAll('.pin[data-kind]')) pin.classList.add('spent');
  for (const button of document.querySelectorAll('#blocks .attach.on')) button.click();
  syncTargets();
  drawMap();
});

// It types the words and sends them. The message then reads as what it is — somebody saying to
// take it on — and there is one path through the console rather than two.
document.getElementById('get-started').addEventListener('click', () => {
  const field = document.getElementById('ask-text');
  field.value = field.value.trim() || 'take these on';
  document.getElementById('ask').requestSubmit();
});

// What comes with a card when it lands. "При помещении идеи на верстак рядом с ней появляется
// связанный проект-карточка либо карточки связанных элементов", and "при записи идеи сперва
// карточка идеи, далее под-идеи (отдельные карточки)… если дочерние тоже декомпозированы,
// ситуация повторяется со сдвигом".
//
// A tree, in other words: the thing, then what it is made of, then what those are made of, each
// generation a step to the right. Bounded, because an idea with forty descendants is a workbench
// nobody can use.
const MOST_KIN = 12;

// "Помещая проект на экран я хочу видеть карточки связанных инстансов, сессий, агентов."
//
// The board is already this tree — a project holds its checkouts, a checkout its sessions, a
// session the agents it started — so the parts of a card are read from `#board` rather than asked
// of the server. The same argument `syncBlocks` reads `#blocks` under: the answer is already on
// the page, and a second source is a second thing to keep in step.
function boardCard(name) {
  const at = name.indexOf(':');
  if (at < 0) return null;
  const kind = name.slice(0, at);
  const id = name.slice(at + 1);
  return document.querySelector(
    `#board [data-kind="${CSS.escape(kind)}"][data-id="${CSS.escape(id)}"]`
  );
}

// The parts of a card: the nearest cards under it, and not their parts. One rule rather than one
// per kind, so a card kind added to the board later opens out without anybody coming back here.
function partsOf(name) {
  const holder = boardCard(name);
  if (!holder) return [];
  return [...holder.querySelectorAll('[data-kind][data-id]')].filter(
    (one) => one.parentElement.closest('[data-kind][data-id]') === holder
  );
}

// Kinds whose insides are behind somebody else's API rather than in the left column. The page
// cannot know whether one has parts without asking, and asking on every board push would be a
// request every two seconds — so these show the control and answer when it is pressed.
const ASK_FOR_PARTS = new Set(['connector', 'column']);

// Only on a card that is a step. An Object does not do anything, so a run starting at one would
// begin by doing nothing, and a control that starts a branch has to be on something that runs.
// Whether this card is a step, asked of the server's own answer rather than of a list here. The
// process panel says what each *step* may do, so a card with an entry in it is a step — and the
// five roles stay in one place, which is the rule `agent_desk/roles.py` is served under.
function isAStep(holder) {
  return Object.hasOwn(processSaid.leave || {}, cardName(holder));
}

function showRunFrom(holder) {
  const button = holder.querySelector('.pin-run');
  if (button) button.hidden = !isAStep(holder);
}

async function runFromHere(holder) {
  const name = cardName(holder);
  try {
    const answer = await fetch('/workbench/run', {
      method: 'POST',
      headers: FORM,
      body: new URLSearchParams({ cards: onBench().map(cardName).join(','), from: name }),
    });
    const said = await answer.json();
    say(said.started ? 'Running from this card.' : said.why || 'It did not start.');
    readRuns();
  } catch {
    say('It did not start.');
  }
}

async function addButton() {
  const label = (prompt('What is the button called?', '') || '').trim();
  if (!label) return;
  const asks = (prompt('And what does it ask?', '') || '').trim();
  try {
    const answer = await fetch('/cards/button', {
      method: 'POST',
      headers: FORM,
      body: new URLSearchParams({ label, prompt: asks }),
    });
    const said = await answer.json();
    await pin({ kind: 'button', id: said.id, label: said.label }, { came: 'made as a button' });
  } catch {
    say('Could not add a button.');
  }
}

/* --- a card that is a button ------------------------------------------------------------------ */
// "Карточка-кнопка… по умолчанию при нажатии просто отправляет указанный в ней запрос, как будто бы
// мы его вписали в поле ввода, только без создания карточки запроса."
//
// The rule that makes it more than a shortcut is the second half:
//
//   "Если кнопка ни к чему не подключена связью — она работает со всем, что выделено; если
//    подключена к чему-то — работает с тем, с чем подключена."
//
// A line on this bench has always been a statement about two cards. From a button it is scope —
// the first time the drawing *does* something rather than describing something. So a button that
// is joined to three cards asks about those three however the selection stands, and one that is
// joined to nothing asks about what is chosen, and about the whole bench when nothing is.
function reaches(holder) {
  const name = cardName(holder);
  const joined = everyTie()
    .flatMap((line) => (line.from === name ? [line.to] : line.to === name ? [line.from] : []))
    .filter((other) => surface?.querySelector(`.pin[data-name="${CSS.escape(other)}"]`));
  if (joined.length) return [...new Set(joined)];
  // Nothing joined: whatever is chosen, and the ordinary default when nothing is — which is what
  // the input field would have sent, because that is what the button is standing in for.
  return null;
}

function saysWhatItReaches(holder) {
  const line = holder.querySelector('.button-scope');
  if (!line) return;
  const joined = reaches(holder);
  line.textContent = joined
    ? `Joined to ${joined.length} card${joined.length === 1 ? '' : 's'}, and asks about ${
        joined.length === 1 ? 'it' : 'those'
      }.`
    : 'Joined to nothing, so it asks about whatever is chosen — or the whole workbench.';
}

async function pressTheButton(holder) {
  const asks = holder.querySelector('textarea[name="prompt"]')?.value?.trim() || '';
  if (!asks) {
    say('That button has nothing to ask yet. Write it on the card.');
    return;
  }
  const joined = reaches(holder);
  const body = new URLSearchParams({
    text: asks,
    thread: activeThread(),
    // Sent by a button, so the bench draws no card for the question — only for what comes back.
    button: 'yes',
    targets: (joined || pinnedTargets().split(',').filter(Boolean)).join(','),
    history: attachedBlocks(),
    notes: ownBlockText(),
  });
  try {
    const answer = await fetch('/blocks', {
      method: 'POST',
      headers: { ...FORM, 'HX-Request': 'true' },
      body,
    });
    if (answer.ok) {
      document.getElementById('blocks').innerHTML = await answer.text();
      if (window.htmx) htmx.process(document.getElementById('blocks'));
      syncBlocks();
      showActiveThread();
    }
  } catch {
    say('It did not send.');
  }
}

// A check reads one thing: an answer card, which already carries both halves of its exchange —
// what was asked and what came back. So "what is it joined to" is the same question a button asks,
// through the same line, and there was no second kind of wire to invent.
function whatItChecks(holder) {
  const judged = holder.querySelector('[data-about]')?.dataset.about || '';
  const joined = (reaches(holder) || []).filter(
    // Not one it has already set aside. A corrected answer arrives joined to the check that asked
    // for it, so without this the gesture builds the second answer that stops the gesture (063).
    (name) => name.startsWith('answer:') && name !== judged
  );
  // The newest, by id: these are ULIDs, so sorting them is sorting by when they were made. A
  // corrected answer is by definition the later one, which is the one to check next.
  return joined.length > 1 ? [joined.slice().sort().pop()] : joined;
}

function saysWhatItChecks(holder) {
  const line = holder.querySelector('.check-scope');
  if (!line) return;
  const on = whatItChecks(holder);
  const joined = (reaches(holder) || []).filter((name) => name.startsWith('answer:')).length;
  line.textContent = !on.length
    ? 'Joined to no answer yet. Draw a line from it to one.'
    : `Reads “${labelOf(on[0])}” — what was asked and what came back.${
        joined > 1 ? ` The newest of the ${joined} it is joined to.` : ''
      }`;
}

// "Карточка проверки потухает и становится серой и неактивной." A check that passed has nothing
// left to say and should stop asking to be read — but it does not disappear, because *that this
// answer was checked* is a fact worth having tomorrow. So: dimmed, folded to its line, and the
// button gone. Pressing it again is still possible, and it is the ordinary way — open the card.
// "Блоки ответа становятся серыми и помещаются в одну очерченную область."
//
// Quarantine, not a bin. A wrong answer is what a right one is compared against, and deleting it
// straight away throws away half of the working-out. So the answer a check failed is dimmed and
// framed, and it is still there — still readable, still joined to everything it was joined to.
//
// Derived rather than stored: the verdict is on the check card and the line to the answer is on
// the bench, so the frame is worked out from those two whenever the card is built. That is what
// makes it survive a reload without a second place to keep it in step with.
function quarantineFor(holder) {
  const name = cardName(holder);
  const failed = Boolean(holder.querySelector('.check-verdict.failed'));
  // What it *judged*, not what it is joined to now. Those are two questions and they part company
  // the moment a corrected answer arrives (063).
  const about = holder.querySelector('[data-about]')?.dataset.about || '';
  const on = about ? [about] : [];
  const ring = surface?.querySelector(`.ring[data-check="${CSS.escape(name)}"]`);

  for (const card of surface?.querySelectorAll(`.pin[data-quarantined="${CSS.escape(name)}"]`) || []) {
    card.classList.remove('quarantined');
    card.removeAttribute('data-quarantined');
  }
  if (!failed || !on.length) {
    ring?.remove();
    return;
  }

  const held = [];
  for (const one of on) {
    const card = surface?.querySelector(`.pin[data-name="${CSS.escape(one)}"]`);
    if (!card) continue;
    card.classList.add('quarantined');
    card.dataset.quarantined = name;
    held.push(one);
  }
  if (!held.length) {
    ring?.remove();
    return;
  }
  const frame = ring || document.createElement('div');
  if (!ring) {
    frame.className = 'ring quarantine';
    frame.dataset.check = name;
    surface.appendChild(frame);
  }
  frame.dataset.holds = held.join(',');
  // What is wrong with it, on the frame. A grey card inside an outline says something is wrong;
  // the sentence says what, and it is the sentence somebody acts on.
  frame.textContent = holder.querySelector('.check-verdict')?.textContent?.trim().slice(0, 200) || '';
  drawRings();
}

function showCheck(holder) {
  const button = holder.querySelector('.pin-check');
  if (!button) return;
  const isCheck = holder.dataset.kind === 'check';
  const verdict = holder.querySelector('.check-verdict.passed') ? 'passed' : '';
  holder.classList.toggle('checked', isCheck && Boolean(verdict));
  button.hidden = !isCheck || Boolean(verdict);
  // Only where there is something to correct. A "try again" on a check nobody has pressed is a
  // button that would ask the same question for no reason.
  const again = holder.querySelector('.pin-again');
  if (again) again.hidden = !isCheck || !holder.querySelector('.check-verdict.failed');
  if (isCheck) {
    saysWhatItChecks(holder);
    quarantineFor(holder);
  }
}

// "Из карантина растут исправленные ответы, и когда всё готово — карантин исчезает."
//
// Asking again, with the two things the last attempt did not have: the answer that failed, and the
// check that failed it. Both travel as cards the gesture named, so the digest describes them —
// an attempt that cannot see what it failed is an attempt at the same answer.
//
// It is not a combine and does not follow the bench's combining rule: what this asks is fixed by
// the console, because "answer it again, and this time satisfy the check" is the whole of the
// gesture and there is nothing about it for anybody to configure.
const HOW_TO_TRY_AGAIN =
  'The answer on the workbench did not pass the check beside it. Answer the original question ' +
  'again, and this time meet the condition the check states. Do not explain what went wrong — ' +
  'give the answer.';

async function tryAgain(holder) {
  // The answer it judged, not the one it would read next. "Try again" means redo the one that
  // failed, and by the time this is offered the check has already stopped reading it.
  const failed = holder.querySelector('[data-about]')?.dataset.about || '';
  if (!failed) {
    say('Press check first — there is nothing to correct yet.');
    return;
  }
  const on = [failed];
  say('Asking again…');
  const body = new URLSearchParams({
    text: HOW_TO_TRY_AGAIN,
    thread: activeThread(),
    button: 'yes',
    gesture: 'again',
    // The failed answer and the check, in that order: what was produced, and what it had to be.
    made_from: [on[0], cardName(holder)].join(','),
    targets: [on[0], cardName(holder)].join(','),
    history: attachedBlocks(),
    notes: ownBlockText(),
  });
  try {
    const answer = await fetch('/blocks', {
      method: 'POST',
      headers: { ...FORM, 'HX-Request': 'true' },
      body,
    });
    if (!answer.ok) {
      say('It did not send.');
      return;
    }
    document.getElementById('blocks').innerHTML = await answer.text();
    if (window.htmx) htmx.process(document.getElementById('blocks'));
    syncBlocks();
    showActiveThread();
  } catch {
    say('It did not send.');
  }
}

async function runTheCheck(holder) {
  const on = whatItChecks(holder);
  try {
    const answer = await fetch('/workbench/check', {
      method: 'POST',
      headers: FORM,
      body: new URLSearchParams({ id: holder.dataset.id, on: on.join(',') }),
    });
    const said = await answer.json();
    if (!said.verdict) {
      say(said.why || 'It could not be checked.');
      return;
    }
    say(`${said.verdict === 'passed' ? 'It passed' : 'It did not pass'} — ${said.why}`);
    // Read back from the server rather than painted here: the verdict is stored, and a page
    // writing its own copy would be a second answer to "what did it decide".
    const body = await fetch(`/cards/check?id=${encodeURIComponent(holder.dataset.id)}`);
    if (body.ok) {
      holder.querySelector('.pin-body').innerHTML = await body.text();
      showCheck(holder);
      // Out of the way, not out of existence. A failed one stays open: it is the thing somebody
      // has to act on, and folding it away would hide the sentence saying what to do.
      if (said.verdict === 'passed') setView(holder, 'hint');
      drawTies();
    }
  } catch {
    say('It could not be checked.');
  }
}

// --- tools: a card with behaviour, kept ---------------------------------------------------------
// "Уникальная карточка, в которую можно закладывать разнообразный функционал… Хранятся в списке под
// проектами, слева снизу." A button and a check both die with the workbench they were made on;
// this is the same card kept under a name and put on any bench, as a fresh card each time.
async function showTools() {
  const into = document.getElementById('kept-tools');
  if (!into) return;
  into.replaceChildren();
  let kept = [];
  try {
    kept = ((await (await fetch('/tools')).json()).tools) || [];
  } catch {
    return;
  }
  if (!kept.length) {
    const none = document.createElement('li');
    none.className = 'saved-none';
    none.textContent = 'nothing kept yet';
    into.appendChild(none);
    return;
  }
  for (const one of kept) {
    const row = document.createElement('li');
    const open = document.createElement('button');
    open.type = 'button';
    open.className = 'saved-open';
    open.textContent = `${one.name} · ${one.kind}`;
    // What it will ask or check, where somebody decides which of six tools they meant.
    open.title = one.said || 'it says nothing yet';
    open.addEventListener('click', () => useTool_(one.name));
    const drop = document.createElement('button');
    drop.type = 'button';
    drop.className = 'saved-drop';
    drop.textContent = '×';
    drop.title = `forget ${one.name}`;
    drop.addEventListener('click', async (event) => {
      event.stopPropagation();
      await fetch('/tools/drop', {
        method: 'POST',
        headers: FORM,
        body: new URLSearchParams({ name: one.name }),
      });
      showTools();
    });
    row.append(open, drop);
    into.appendChild(row);
  }
}

// Named with a trailing underscore because `useTool` is the tool *strip* — the pointer modes — and
// two functions called the same thing in one file is the bug nobody finds by reading.
async function useTool_(name) {
  try {
    const made = await (
      await fetch('/tools/use', {
        method: 'POST',
        headers: FORM,
        body: new URLSearchParams({ name }),
      })
    ).json();
    if (!made.id) {
      say(made.why || 'It could not be put on the workbench.');
      return;
    }
    await pin({ kind: made.kind, id: made.id, label: made.label }, { came: 'taken from the tools' });
  } catch {
    say('It could not be put on the workbench.');
  }
}

// On the document rather than on the form: the board fragment is replaced on every push, and a
// listener bound to the form went with the first one — the field then did nothing, silently, and
// only after a push nobody was watching for.
document.addEventListener('submit', async (event) => {
  if (event.target.id !== 'describe-tool') return;
  event.preventDefault();
  const field = event.target.querySelector('input[name="said"]');
  const said = field.value.trim();
  if (!said) return;
  say('Making it…');
  try {
    const made = await (
      await fetch('/tools/describe', {
        method: 'POST',
        headers: FORM,
        body: new URLSearchParams({ said }),
      })
    ).json();
    if (!made.id) {
      say(made.why || 'It could not be made.');
      return;
    }
    field.value = '';
    // On the workbench and not in the list: keeping it is the press that already exists on the
    // card, so a tool nobody wanted twice leaves nothing behind.
    await pin({ kind: made.kind, id: made.id, label: made.label }, { came: 'made from a description' });
    say(`Made “${made.label}”. Keep it as a tool from the card if you want it again.`);
  } catch {
    say('It could not be made.');
  }
});

async function keepAsATool(holder) {
  const name = (prompt('Keep it as a tool called:', holder.querySelector('.pin-label')?.textContent?.trim() || '') || '').trim();
  if (!name) return;
  const kept = await (
    await fetch('/tools', {
      method: 'POST',
      headers: FORM,
      body: new URLSearchParams({ card: cardName(holder), name }),
    })
  ).json();
  say(kept.name ? `Kept “${kept.name}”.` : kept.why || 'It could not be kept.');
  showTools();
}

async function addCheck() {
  const label = (prompt('What is the check called?', '') || '').trim();
  if (!label) return;
  const said = (
    prompt(
      'And what does the answer have to be?\n\n"contains ERROR", "does not contain TODO", "is JSON", "shorter than 400" — or a sentence, which is asked instead.',
      ''
    ) || ''
  ).trim();
  try {
    const answer = await fetch('/cards/check', {
      method: 'POST',
      headers: FORM,
      body: new URLSearchParams({ label, said }),
    });
    const made = await answer.json();
    await pin({ kind: 'check', id: made.id, label: made.label }, { came: 'made as a check' });
  } catch {
    say('Could not add a check.');
  }
}

function showPress(holder) {
  const button = holder.querySelector('.pin-press');
  if (!button) return;
  button.hidden = holder.dataset.kind !== 'button';
  if (!button.hidden) saysWhatItReaches(holder);
}

function showParts(holder) {
  const button = holder.querySelector('.pin-parts');
  if (!button) return;
  // Hidden rather than dead. A control that does nothing when pressed is worse than no control:
  // the first press teaches somebody it is broken, and they stop pressing the ones that work.
  button.hidden =
    !ASK_FOR_PARTS.has(holder.dataset.kind) && partsOf(cardName(holder)).length === 0;
}

// The parts of a card whose insides are not on the page. "Тот же механизм раскрытия, но через
// сеть: у коннектора спрашивают, что у него внутри, уровень за уровнем."
async function askForParts(holder) {
  const kind = holder.dataset.kind;
  const id = holder.dataset.id;
  try {
    const answer = await fetch(
      `/cards/${encodeURIComponent(kind)}/parts?id=${encodeURIComponent(id)}`
    );
    const said = await answer.json();
    return said.parts || [];
  } catch {
    return [];
  }
}

// Which cards have been opened out already, so pressing twice does not draw the lines twice.
const openedOut = new Set();

// One level per press. "Раскрытие ленивое: проект с пятью инстансами и сорока сессиями, раскрытый
// целиком и сразу, это сорок карточек, которые никто не просил." The way down is to press the card
// that arrived, which is also the only way anybody ends up with forty of them on purpose.
async function openItsParts(holder) {
  const name = cardName(holder);
  const what = holder.dataset.kind;
  // Off the page where the page has it, off the network where it does not. One press, one meaning,
  // whichever side of the wire the answer is on.
  const parts = ASK_FOR_PARTS.has(what)
    ? await askForParts(holder)
    : partsOf(name).map((one) => ({
        kind: one.dataset.kind,
        id: one.dataset.id,
        label: one.dataset.label,
      }));
  if (!parts.length) return say(`Nothing inside this ${what} that this console can read.`);
  const at = placed.get(name) || { x: 20, y: 20 };
  let down = 0;
  for (const part of parts) {
    const under = `${part.kind}:${part.id}`;
    if (!surface.querySelector(`.pin[data-name="${CSS.escape(under)}"]`)) {
      await pin(
        { kind: part.kind, id: part.id, label: part.label },
        {
          at: { x: at.x + CARD_WIDTH + GAP * 2, y: at.y + down * 140 },
          quiet: true,
          came: `opened out of the ${what}`,
        }
      );
    }
    if (!openedOut.has(`${name} ${under}`)) {
      openedOut.add(`${name} ${under}`);
      ownTies.push({ from: name, to: under, says: 'part of' });
    }
    down += 1;
  }
  drawTies();
  syncTargets();
}

async function bringItsKin(card, at) {
  if (card.kind !== 'idea') return;
  let brought = 0;
  try {
    const response = await fetch(`/ideas/${encodeURIComponent(card.id)}/kin`);
    if (!response.ok) return;
    const kin = await response.json();

    // The project it belongs to, beside it.
    if (kin.project) {
      await pin(
        { kind: 'project', id: kin.project.key, label: kin.project.name },
        {
          at: { x: at.x - CARD_WIDTH - GAP * 3, y: at.y },
          quiet: true,
          came: 'brought in as this idea’s project',
        }
      );
      ownTies.push({
        from: `project:${kin.project.key}`,
        to: `idea:${card.id}`,
        says: 'is about',
      });
    }

    // What it is made of, one generation at a time, each a step to the right.
    const walk = async (parents, depth) => {
      for (const child of parents) {
        if (brought >= MOST_KIN || depth > 3) return;
        brought += 1;
        await pin(
          { kind: 'idea', id: child.id, label: child.summary },
          {
            at: { x: at.x + depth * (CARD_WIDTH + GAP * 2), y: at.y + brought * 40 },
            quiet: true,
            came: 'brought in as part of another idea',
          }
        );
        ownTies.push({ from: `idea:${child.parent}`, to: `idea:${child.id}`, says: 'part of' });
        await walk(child.children || [], depth + 1);
      }
    };
    await walk(kin.children || [], 1);
  } catch {
    // A card that arrived alone is still a card.
  }
  drawTies();
}

async function pin(card, how) {
  // Against the *cards* on the surface, by their own name. Looking for `[data-kind][data-id]`
  // matched the idea lines *inside* a block card — the conversation is on the workbench now, so
  // the markup it renders is inside `#pins` too — and `pin` therefore returned early every time,
  // which is why an idea never became a card of its own.
  const name = `${card.kind}:${card.id}`;
  if (surface?.querySelector(`.pin[data-name="${CSS.escape(name)}"]`)) return;
  const holder = document.createElement('div');
  holder.className = 'pin';
  // Focusable, because that is what the arrow keys move: a card somebody tabbed
  // or clicked to is the one that answers a key press.
  holder.tabIndex = 0;
  holder.dataset.kind = card.kind;
  holder.dataset.id = card.id;
  // Its own name, so a line can find it without re-deriving the pair every time it is drawn.
  holder.dataset.name = `${card.kind}:${card.id}`;
  // Not `draggable`: on the surface a card is moved by its head with the pointer, and the HTML5
  // drag would fight that. `×` is how a card leaves.
  holder.dataset.deep = 'no';
  holder.dataset.view = 'hint';
  // Where it came from, in the words a person would use, and when (045). Said by whoever makes the
  // card, because that is the only place that knows; a caller that does not say leaves the line off
  // rather than having one invented for it.
  holder.dataset.came = how?.came || '';
  holder.dataset.cameAt = String(how?.cameAt || Date.now());
  holder.innerHTML = `<div class="pin-head"><span class="pin-live" title="in the next message — press to leave it out">●</span>
    <button type="button" class="pin-role" title="what this is in the process"></button>
    <span class="pin-kind">${card.kind}</span>
    <span class="pin-label"></span>
    <button type="button" class="pin-view" title="a line — press for what it is">a line</button>
    <button type="button" class="pin-press" title="send what this button asks" hidden>press</button>
    <button type="button" class="pin-check" title="read what this is joined to and say whether it is what it had to be" hidden>check</button>
    <button type="button" class="pin-again" title="ask the question again, this time meeting the check" hidden>try again</button>
    <button type="button" class="pin-run" title="run this card and everything after it" hidden>run from here</button>
    <button type="button" class="pin-answers" title="what each model answered, side by side" hidden>answers</button>
    <button type="button" class="pin-parts" title="put what this is made of on the workbench" hidden>parts</button>
    <button type="button" class="pin-deep" title="send its whole transcript, not just the summary">brief</button>
    <button type="button" class="pin-off" title="stop talking about this">×</button></div>
    <p class="pin-came"></p>
    <div class="pin-body">reading…</div>`;
  holder.querySelector('.pin-label').textContent = card.label || card.id;
  writeCame(holder);
  pins.appendChild(holder);
  showRole(holder);
  // `exact` is for a position that was *remembered* rather than worked out — restoring the bench,
  // undoing, opening a saved workbench. Without it every restore ran the layout through collision
  // avoidance again, so a bench came back close to where it was left rather than where it was left
  // and drifted a little further on each load. `bringItsKin` does want avoidance: it asks for a
  // spot beside another card and does not mind which side of it ends up free.
  place(holder, how?.under ? spotUnder([how.under]) : how?.at || null, {
    avoid: !how?.exact,
  });
  if (how?.under) {
    ownTies.push({ from: how.under, to: cardName(holder), says: 'wrote' });
    // Brought by the conversation rather than dropped by a person, which is what decides whether
    // it goes away when the conversation is folded.
    holder.dataset.brought = 'yes';
  }
  syncTargets();
  // What it is made of, and what it belongs to. Not for a card brought *by* one of these, or a
  // tree would fetch itself for ever.
  if (!how?.quiet) bringItsKin(card, placed.get(cardName(holder)) || { x: 20, y: 20 });

  try {
    const url = `/cards/${encodeURIComponent(card.kind)}?id=${encodeURIComponent(card.id)}`;
    const response = await fetch(url);
    holder.querySelector('.pin-body').innerHTML = response.ok
      ? await response.text()
      : '<p class="empty small">could not read this one</p>';
    nameItProperly(holder, card);
    writeHint(holder);
    showParts(holder);
    showRunFrom(holder);
    showPress(holder);
    showCheck(holder);
    // Folded or open, as it was left. After the body rather than before it: `full` fetches the
    // technical half *into* the body, and the body is replaced by the line above.
    if (how?.shown && how.shown !== holder.dataset.view) setView(holder, how.shown);
    settleOverlaps();
  } catch {
    holder.querySelector('.pin-body').innerHTML = '<p class="empty small">could not read this one</p>';
  }
  syncTargets();
}

// The one line that says how a card got here. "Это ровно то же требование, которое в этом проекте
// уже применено к статусам: показывать, на основании чего сказано."
//
// What it was made *from* is deliberately not in here: that is the line drawn to it. Bringing an
// idea's project in draws a line from the project, an answer that writes an idea down joins the
// two, a template's steps arrive with the lines between them — saying it twice would be two copies
// of one fact, and they would disagree the first time somebody rubbed a line out.
function writeCame(holder) {
  const line = holder.querySelector('.pin-came');
  if (!line) return;
  const came = holder.dataset.came;
  line.hidden = !came;
  line.textContent = came ? `${came} · ${howLongAgo(Number(holder.dataset.cameAt) || 0)}` : '';
}

// "Когда", in the units somebody actually thinks in. Ten seconds ago and eleven minutes ago are
// different answers to "why is this here"; the exact time on a clock is not.
function howLongAgo(then) {
  if (!then) return 'just now';
  const seconds = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (seconds < 45) return 'just now';
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

// What a folded card says about itself.
//
// "Сейчас плохо отображаются хинты, практически не видно что из себя представляют" — because a
// folded card showed its title and nothing else, and a title is a name rather than a description.
// The sentence written *about* the card (028-card-descriptions.sql) is the thing that says what it
// is, and every card kind renders one somewhere in its body.
//
// So the hint is lifted out of the body into the head, where it survives the body being folded
// away. Two lines, which is the size that was asked for; the fallbacks below are in the order of
// how much they say, and the last of them is better than an empty line under a title.
const HINT_ORDER = ['.card-said', '.plain-what', '.plain-doing', '.last-line', '.card-body p', 'p'];

function writeHint(holder) {
  const body = holder.querySelector('.pin-body');
  if (!body) return;
  let said = '';
  for (const where of HINT_ORDER) {
    const found = [...body.querySelectorAll(where)]
      .map((node) => (node.textContent || '').trim())
      .find((text) => text.length > 2);
    if (found) {
      said = found;
      break;
    }
  }
  let line = holder.querySelector('.pin-hint');
  if (!said) {
    line?.remove();
    return;
  }
  if (!line) {
    line = document.createElement('p');
    line.className = 'pin-hint';
    holder.querySelector('.pin-head')?.after(line);
  }
  line.textContent = said;
  line.title = said;
}

// A card put on the bench by something that did not know its name — a template being used, a
// sketch being placed — arrives with none, and the head then shows its raw id. An identifier is
// the one thing a card's name must never be, so the body is asked once it has loaded.
function nameItProperly(holder, card) {
  if (card.label) return;
  const said = holder.querySelector('[data-label]')?.dataset.label?.trim();
  if (said) holder.querySelector('.pin-label').textContent = said;
}

// The three a card has, and they are the three the pool named: "1 — хинт, то что видно в
// максимально свёрнутом виде; 2 — метадата, то что идёт в контекст по умолчанию и отображается
// при добавлении в рабочее пространство; 3 — фул-инфо, буквально вся информация, по умолчанию
// свёрнута".
//
// One control cycling three states rather than two controls, because they are one question —
// how much of this do I want to see — and answering it in two places is how somebody ends up
// with a card that is folded *and* technical.
const VIEWS = ['hint', 'metadata', 'full'];
const VIEW_SAYS = { hint: 'a line', metadata: 'what it is', full: 'everything' };

// "Вместе с хинтом — сопутствующая информация: визуальные индикаторы или числа, не текст, плюс
// связанные/дочерние."
//
// A hint is one line, so what else it can carry has to be countable rather than said. What a card
// is joined to is a number this page already knows, and it is the number that answers "is there
// more of this than I can see" — which is the question a folded card raises.
// How many lines reach this card, given rather than counted. Counted here it was one walk over
// every line, for every card, on every redraw — which is the shape that turns a hundred cards into
// a surface that will not pan.
function markHintCounts(holder, joined) {
  let dot = holder.querySelector('.pin-joined');
  if (!joined) {
    dot?.remove();
    return;
  }
  if (!dot) {
    dot = document.createElement('span');
    dot.className = 'pin-joined';
    holder.querySelector('.pin-label')?.after(dot);
  }
  dot.textContent = String(joined);
  dot.title = `joined to ${joined} other card${joined === 1 ? '' : 's'}`;
}

function setView(holder, view) {
  holder.dataset.view = view;
  // "Когда" is written when the card is made and read when somebody opens it, so it is worked out
  // again here. A tab left open for an hour would otherwise still be saying "just now", which is
  // the one thing a line about provenance must not do.
  writeCame(holder);
  const button = holder.querySelector('.pin-view');
  if (button) {
    button.textContent = VIEW_SAYS[view];
    button.title =
      view === 'hint'
        ? 'just the line — press for what it is'
        : view === 'metadata'
          ? 'what it is — press for everything, including the technical detail'
          : 'everything, including the technical detail — press to fold it back to a line';
  }
  // `full` fetches the whole thing — the console, how long it has been up, the tokens — because
  // a card does not carry that until somebody asks: "фул-дата открывается только если
  // пользователь намеренно нажмёт на кнопку".
  if (view === 'full' && !holder.dataset.gotFull) {
    holder.dataset.gotFull = 'yes';
    const [kind, ...rest] = (holder.dataset.name || '').split(':');
    if (kind && kind !== 'note' && kind !== 'block') {
      fetch(`/cards/${encodeURIComponent(kind)}/full?id=${encodeURIComponent(rest.join(':'))}`)
        .then((response) => (response.ok ? response.text() : ''))
        .then((html) => {
          if (!html) return;
          const where = holder.querySelector('.technical-only') || holder.querySelector('.pin-body');
          where.insertAdjacentHTML('beforeend', html);
          settleOverlaps();
        })
        .catch(() => {});
    }
  }

  const inner = holder.querySelector('[data-detail]');
  if (inner) {
    const technical = view === 'full';
    inner.dataset.detail = technical ? 'technical' : 'plain';
    const plain = inner.querySelector('.plain-only');
    const detail = inner.querySelector('.technical-only');
    if (plain) plain.hidden = technical;
    if (detail) detail.hidden = !technical;
  }
  settleOverlaps();
}

document.addEventListener('click', (event) => {
  if (event.target.classList.contains('pin-view')) {
    const holder = event.target.closest('.pin');
    const at = VIEWS.indexOf(holder.dataset.view || 'metadata');
    setView(holder, VIEWS[(at + 1) % VIEWS.length]);
    return;
  }

  // "Карточка с кнопкой пуск… Отдельная карточка, а не кнопка на панели." The complaint is about
  // the *panel*: one button that runs everything cannot start the branch somebody is thinking
  // about. This is that button, on the card it starts from.
  if (event.target.classList.contains('pin-press')) {
    pressTheButton(event.target.closest('.pin'));
    return;
  }

  if (event.target.classList.contains('pin-check')) {
    runTheCheck(event.target.closest('.pin'));
    return;
  }

  if (event.target.classList.contains('pin-again')) {
    tryAgain(event.target.closest('.pin'));
    return;
  }

  if (event.target.classList.contains('pin-answers')) {
    showAnswersOn(event.target.closest('.pin'));
    return;
  }

  if (event.target.classList.contains('pin-run')) {
    runFromHere(event.target.closest('.pin'));
    return;
  }

  if (event.target.classList.contains('pin-parts')) {
    openItsParts(event.target.closest('.pin'));
    return;
  }

  if (event.target.classList.contains('pin-off')) {
    event.target.closest('.pin').remove();
    syncTargets();
    return;
  }

  // Brief by default, and the whole transcript only when somebody says so: the difference is the
  // size of the prompt and how long the answer takes.
  if (event.target.classList.contains('pin-deep')) {
    const holder = event.target.closest('.pin');
    const deep = holder.dataset.deep !== 'yes';
    holder.dataset.deep = deep ? 'yes' : 'no';
    holder.classList.toggle('deep', deep);
    event.target.textContent = deep ? 'full' : 'brief';
    syncTargets();
    return;
  }

  if (event.target.classList.contains('attach')) {
    event.target.classList.toggle('on');
    event.target.textContent = event.target.classList.contains('on')
      ? 'in context'
      : 'use as context';
    syncTargets();
    return;
  }

  // Clicking a card is the same act as dragging it in: both mean "show me this one". The twist
  // is left alone, because opening a node and opening a card are different questions and the
  // triangle is the one control that has always meant the first.
  const opener = event.target.closest('.node-open');
  const name = event.target.closest('.card-name, .node-name');
  const card = (opener || name)?.closest('[data-kind]');
  if (!card) return;
  event.preventDefault();
  pin(
    { kind: card.dataset.kind, id: card.dataset.id, label: card.dataset.label },
    { came: 'picked from the overview' }
  );
});

let dragged = null;

document.addEventListener('dragstart', (event) => {
  const card = event.target.closest('[data-kind]');
  if (!card) return;
  dragged = {
    kind: card.dataset.kind,
    id: card.dataset.id,
    label: card.dataset.label,
    project: card.closest('.project')?.dataset.project,
    fromPins: !!card.closest('#pins'),
    // An idea the desk proposed and nobody has looked at yet. Read here rather than after the
    // drop, because the card it was read from is in a column this drop may well replace.
    unlooked: card.classList.contains('unlooked'),
  };
  event.dataTransfer.setData('text/plain', card.dataset.label || '');
  event.dataTransfer.effectAllowed = 'copyMove';
  card.classList.add('dragging');
  document.body.classList.add('dragging-card');
});

document.addEventListener('dragend', (event) => {
  event.target.closest?.('[data-kind]')?.classList.remove('dragging');
  document.body.classList.remove('dragging-card');
  // A card on the bench is moved with the pointer and removed with its `×`, so a stray HTML5
  // drag no longer takes one off. Dragging a card *in* is unchanged.
  dragged = null;
});

function zoneOf(event) {
  // The output and the staging area under it are one target: dropping a card anywhere in the
  // middle means "this is what the next message is about".
  return event.target.closest(
    '#bench-canvas, [data-drop="project"], [data-drop="idea"], [data-drop="ungroup"]'
  );
}

document.addEventListener('dragover', (event) => {
  const zone = zoneOf(event);
  if (!zone || !dragged) return;
  event.preventDefault();
  zone.classList.add('drop-target');
});

document.addEventListener('dragleave', (event) => zoneOf(event)?.classList.remove('drop-target'));

document.addEventListener('drop', (event) => {
  const zone = zoneOf(event);
  if (!zone || !dragged) return;
  event.preventDefault();
  zone.classList.remove('drop-target');
  dragged.handled = true;

  if (zone.id === 'bench-canvas') {
    if (!dragged.fromPins) {
      const { kind, id, unlooked } = dragged;
      pin(dragged, { came: 'dropped on the workbench' }).then(() => {
        // "Я перетягиваю твою идею на верстак, начинаю задавать тебе вопросы." A proposal is an
        // idea nobody holds the context of yet, and the way to come to hold it is to ask about it
        // — which is what an enquiry is, and an enquiry needs a root. This is that root.
        //
        // Only a proposal, and only when the chat has no beginning yet. Every idea becoming the
        // root of an enquiry would hijack an ordinary bench, and replacing a beginning somebody
        // set is the console overruling them about what they are working on.
        if (!unlooked || surface.querySelector('.pin.beginning')) return;
        beginFrom(`${kind}:${id}`);
        say('Asking about this one — what you ask next hangs off it.');
      });
    }
    document.getElementById('ask-text').focus();
    return;
  }

  // One idea onto another: they are one piece of work, and somebody just said so. Onto the header
  // instead: take it back out of whatever it was under.
  const grouping = zone.dataset.drop === 'idea' || zone.dataset.drop === 'ungroup';
  if (grouping && dragged.kind === 'idea') {
    const parent = zone.dataset.drop === 'idea' ? zone.dataset.id : '';
    if (parent === dragged.id) return;
    fetch(`/ideas/${encodeURIComponent(dragged.id)}/parent`, {
      method: 'POST',
      headers: { 'HX-Request': 'true' },
      body: new URLSearchParams({ parent }),
    })
      .then((response) => (response.ok ? response.text() : null))
      .then((html) => {
        if (!html) return;
        document.getElementById('idea-list').innerHTML = html;
        filterIdeas();
      });
    return;
  }
  if (grouping) return;

  // Onto a project card: what travels is the repository the dragged card belongs to.
  const into = zone.dataset.project;
  const from = dragged.kind === 'project' ? dragged.id : dragged.project;
  if (!into || !from || into === from) return;
  fetch(`/projects/${encodeURIComponent(into)}/members`, {
    method: 'POST',
    headers: { 'HX-Request': 'true' },
    body: new URLSearchParams({ repo_key: from }),
  })
    .then((response) => (response.ok ? response.text() : null))
    .then((html) => { if (html) document.getElementById('board').innerHTML = html; });
});

/* --- the third view of a card ------------------------------------------------------------------- */
// A card has three: the hint in the overview, the metadata that opens on the workbench, and this —
// everything the session has said. It is fetched when it is asked for and not before, because it
// is a console's worth of text and most cards are never opened this far.
document.addEventListener(
  'toggle',
  async (event) => {
    const whole = event.target;
    if (!whole.classList?.contains('whole') || !whole.open) return;
    const body = whole.querySelector('.whole-body');
    if (!body || body.dataset.read) return;
    body.dataset.read = 'yes';
    try {
      const response = await fetch(`/sessions/${encodeURIComponent(body.dataset.tail)}/tail`);
      if (response.ok) body.innerHTML = await response.text();
    } catch {
      body.textContent = 'could not read it';
    }
  },
  true
);

/* --- what this one is about ------------------------------------------------------------------- */
// "При наведении на идею/блокер прочее — подсвечивается проект к которому он относится."
//
// A pool of sixty thoughts says nothing about where any of them would land, and neither does a
// column of blockers. The relation exists in the data already — an idea carries a project key and
// so does a blocker — and pointing at one is the cheapest possible way to ask for it.
//
// Hover only, and nothing is clicked or changed: this is a question somebody asks with the mouse
// and takes back by moving it.
function lightUp(key) {
  for (const card of document.querySelectorAll('[data-kind="project"]')) {
    card.classList.toggle('lit', Boolean(key) && card.dataset.id === key);
  }
}

document.addEventListener('mouseover', (event) => {
  const about = event.target.closest('[data-about]');
  lightUp(about ? about.dataset.about : '');
});

document.addEventListener('mouseleave', () => lightUp(''), true);

/* --- the workbench, as a surface you move things about on ------------------------------------- */
// Asked for as "давай сделаем верстак чем-то похожим на app.diagrams.net": cards you place where
// you want them, joined by lines, on a surface you pan and zoom.
//
// Vanilla, because there is no JavaScript build step here (docs/adr/0003) and a diagramming
// library is exactly the kind of thing that arrives with one. What that costs is the features
// nobody asked for — there are no waypoints, no snapping, no undo. What it buys is that the whole
// thing is one screen of code in a file somebody can read.
//
// Two coordinate systems, and keeping them apart is most of the work. A card's `x`/`y` are in
// *surface* space and never change when you pan or zoom; the surface carries one transform. So a
// line between two cards is drawn from their stored positions and is right at any zoom, without
// measuring anything.
const surface = document.getElementById('bench-surface');
const canvas = document.getElementById('bench-canvas');
const ties = document.getElementById('bench-ties');

const CARD_WIDTH = 260;
// Where a new card lands: down and to the right of the last one, the way a stack of paper falls.
const STEP = 28;

let view = { x: 0, y: 0, scale: 1 };
let placed = new Map();
let tieList = [];

// What the layout, the lines and the frames all key a card by.
//
// `data-name` first, and that is not belt and braces: a copy taken for a group carries the same
// `kind` and `id` as the card it was copied from, and a name derived from those would have the
// copy's position overwrite the original's the moment it was placed. Every card that has ever
// been created here sets `data-name`; the fallback is for a node that somehow has not.
// The cards that are actually on the bench.
//
// A card that has been put away with the conversation is still in the document — that is how it
// comes back — and every count, every line and every reading of the bench as a process was
// including it. What that looked like: a corner of the surface filled with lines going to nothing,
// and a panel reporting seven steps that have not said what they need, about cards nobody can see.
//
// One helper, so the answer to "what is on the bench" is given in one place.
function onBench(what = '.pin[data-kind]') {
  return [...(surface?.querySelectorAll(what) || [])].filter(
    (pin) => !pin.classList.contains('put-away')
  );
}

function cardName(pin) {
  return pin.dataset.name || `${pin.dataset.kind}:${pin.dataset.id}`;
}

// The workbench is a thing in the store, not a state of this page (040-bench.sql).
//
// It used to be neither: `agent-desk:bench-layout` held where every card *was*, and nothing held
// *which cards*, so a reload restored the positions of an empty bench. An investigation, a
// drawing, a prototype and a set of cards laid out by hand all lasted exactly as long as the tab.
//
// Which cards are kept, and why the exceptions are exceptions:
//
//   * a **block** card is kept for its position only — the conversation brings it back from the
//     thread by itself, and re-creating it here as well would put two of it on the surface;
//   * a **note** is not kept at all, because its own placeholder promises it "is gone when this
//     tab is", and a promise that specific is not quietly broken by a schema;
//   * a **copy**, a **collection** and a card inside a **ring** each stand for a gesture that is
//     still happening rather than for a card somebody put down.
function benchState() {
  return onBench('.pin[data-kind]:not(.copy):not(.collection):not(.own)')
    // A note lives in the page and a promise stands for something that does not exist. Writing
    // either down would bring it back on the next load as a card about nothing.
    .filter((pin) => pin.dataset.kind !== 'note' && pin.dataset.kind !== 'promise')
    .map((pin) => ({
      name: cardName(pin),
      kind: pin.dataset.kind,
      id: pin.dataset.id,
      label: pin.querySelector('.pin-label')?.textContent?.trim() || '',
      at: placed.get(cardName(pin)),
      shown: pin.dataset.view || 'hint',
      spent: pin.classList.contains('spent'),
      // Whether somebody put it where it is. The page has always known this and always forgot it
      // on reload, so a bench arranged by hand became sweepable again by the next morning (042).
      by_hand: pin.dataset.moved === 'yes',
      came: pin.dataset.came || '',
      came_at: Number(pin.dataset.cameAt) || 0,
    }))
    .filter((one) => one.at);
}

// Nothing is written until the surface has been restored. The first thing this script does after
// the page opens is draw the conversation, and every card it draws asks for the bench to be
// written down — so without this the empty surface of the first millisecond would be saved over
// the bench somebody left.
let restored = false;

// Written once the pointer has been still for a moment, not on every event. `place` is called at
// the rate a pointer reports, which on a fast mouse is over a hundred times a second.
let writing = 0;

// Whether the write now waiting includes somebody *moving* a card, which is the one part of the
// surface the console also changes on its own (041-bench-undo.sql).
//
// A card is placed before its body arrives and grows when it does, so `settleOverlaps` lays its
// neighbours out again — several times, as the bodies land. Treated as changes, those made
// *opening the page* undoable: measured at three steps and twenty cards moved on one ordinary
// load. Undo then walked back through the console tidying up after itself, which from the outside
// is a button that appears to do nothing.
//
// The split that works is not "who wrote this" but "what changed". Which cards are on the bench,
// whether one is folded, whether one is left out of the message, and the lines between them are
// things only a person changes, so the store can tell on its own and nothing has to be flagged.
// Position is the exception, and this is the flag for it — set by the three gestures that move a
// card on purpose. A gesture added later that forgets to set it costs one un-undoable move; the
// other polarity cost an undo button that did nothing on every page load.
let movedByHand = false;

function moveWasDeliberate() {
  movedByHand = true;
  rememberLayout();
}

function rememberLayout() {
  if (!restored) return;
  clearTimeout(writing);
  writing = setTimeout(() => {
    fetch('/workbench/kept', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      // What `benchState` returns, unchanged. The first version of this reshaped it on the way
      // out and got the reshaping wrong — the position went in twice, once as `x`/`y` and once as
      // the `at` it was spread from, and the route dropped every card in the message for being
      // unreadable. A bench that saved itself perfectly as nothing, silently, on every write. So
      // there is one shape and it is this one; the route reads the position where the page keeps
      // it rather than where it would rather have it.
      // Which chat's bench this is. "The workbench belongs to the chat" was already what the page
      // said when somebody switched tabs; saying it to the store is what makes it true across a
      // reload, and what stops one chat's clear from being the other chat's deletion (044).
      body: JSON.stringify({ cards: benchState(), moved: movedByHand, thread: activeThread() }),
    }).catch(() => {
      // A console whose server has gone still lets you move cards about. It will be written the
      // next time one moves and the server answers.
    });
    movedByHand = false;
  }, 400);
}

// What the store was left holding, handed to the page rather than fetched by it — see the comment
// beside `#bench-kept` in board.html.
function keptBench() {
  try {
    return JSON.parse(document.getElementById('bench-kept')?.textContent || '[]');
  } catch {
    return [];
  }
}

// The positions first, then the cards. The positions have to be in `placed` before anything is
// drawn, because `syncBlocks` places a block card the moment it creates one and would otherwise
// stack the whole conversation in the corner before the layout arrived.
function recallLayout() {
  placed = new Map(keptBench().map((one) => [one.name, { x: one.x, y: one.y }]));
}

// Put the workbench back the way it was before the last thing that changed it.
//
// One undo for everything, because everything that changes the surface already goes through the
// same two writes (041-bench-undo.sql). Joining two cards, expanding a project into forty, laying
// the bench out in columns, drawing a whole process — all of them come back, and none of them had
// to know this exists.
//
// Three things have to happen in this order, and each of them is a way it can go wrong.
//
// **The pending write is cancelled first.** A drag half a second ago has a write waiting; letting
// it land after the undo would put the state back that the undo just took away.
//
// **Writing is switched off while the surface is rebuilt.** `clearBench` and every `pin` ask for
// the bench to be written down, and the surface is not the restored one until the last of them
// has run. Without this the undo saves itself over the thing it restored.
//
// **What to draw comes back with the answer.** Fetching it afterwards would read a bench the page
// is about to overwrite, which is the same race one step further along.
async function undoBench() {
  clearTimeout(writing);
  let said;
  try {
    said = await (
      await fetch('/workbench/undo', {
        method: 'POST',
        headers: FORM,
        body: new URLSearchParams({ thread: activeThread() }),
      })
    ).json();
  } catch {
    return say('The console did not answer, so nothing was changed.');
  }
  if (!said.undone) return say('Nothing to go back to — this is how the workbench started.');
  restored = false;
  clearBench();
  layOut(said.cards);
  restored = true;
  syncTargets();
  await loadTies();
  drawMap();
  say('Put back the way it was.');
}

// Put a set of stored cards on an empty surface. Shared by the three things that do it — the page
// opening, switching to another chat, and undoing — because they differ only in where the cards
// came from, and three copies of this loop is three places for the next card property to be
// forgotten in.
//
// `pin` is not awaited: it puts the card in the document before it goes to fetch the body, so by
// the time this returns the surface is populated and `syncBlocks` will not draw a second copy of
// anything.
function layOut(cards) {
  for (const one of cards) {
    // Brought back by the conversation, not by us. Its place is remembered so that `syncBlocks`
    // puts it where it was rather than stacking it in the corner. Both halves of an exchange: the
    // answer is drawn from the same source as the question and is restored the same way.
    if (one.kind === 'block' || one.kind === 'answer') {
      placed.set(one.name, { x: one.x, y: one.y });
      continue;
    }
    pin(
      { kind: one.kind, id: one.card_id, label: one.label },
      {
        at: { x: one.x, y: one.y },
        quiet: true,
        shown: one.shown,
        exact: true,
        // Where it came from originally, not "restored": how a card got onto the bench is a fact
        // about the card, and reloading a page is not a way of making one.
        came: one.came,
        cameAt: one.came_at,
      }
    );
    const node = surface?.querySelector(`.pin[data-name="${CSS.escape(one.name)}"]`);
    if (!node) continue;
    node.classList.toggle('spent', !!one.spent);
    // A card somebody placed stays a card somebody placed. Without this the console's own layout
    // was free to sweep a hand-made arrangement on the first load after it was made.
    if (one.by_hand) node.dataset.moved = 'yes';
  }
}

// The workbench of the chat somebody has just switched to.
//
// The page has always cleared the surface here and said, correctly, that the workbench belongs to
// the chat — it simply had nowhere to keep the other chat's one, so switching was a clear and
// switching back showed an empty bench. Worse, once the bench was in the store the clear was
// *written down*: switching chats deleted the bench you were switching away from.
async function benchOfThisChat() {
  const thread = activeThread();
  restored = false;
  clearBench();
  try {
    const said = await (
      await fetch(`/workbench/kept?thread=${encodeURIComponent(thread)}`)
    ).json();
    // Somebody switching quickly is somebody whose first answer is no longer the right one.
    if (activeThread() === thread) {
      layOut(said.cards);
      // After the cards, because the mark goes on one of them.
      markBeginning(said.start || '');
    }
  } catch {
    // An empty surface, which is what it used to be every time.
  }
  restored = true;
  syncTargets();
  await loadTies();
  drawMap();
}

function beganWith() {
  try {
    return JSON.parse(document.getElementById('bench-began')?.textContent || '""');
  } catch {
    return '';
  }
}

function restoreBench() {
  layOut(keptBench());
  markBeginning(beganWith());
  restored = true;
  syncTargets();
}

function applyView() {
  if (!surface) return;
  drawMap();
  surface.style.transform = `translate(${view.x}px, ${view.y}px) scale(${view.scale})`;
  // The grid moves with it. Without this, panning an empty patch of surface looks like nothing
  // happened at all, which is the one thing a canvas has to get right.
  if (canvas) {
    canvas.style.backgroundSize = `${22 * view.scale}px ${22 * view.scale}px`;
    canvas.style.backgroundPosition = `${view.x}px ${view.y}px`;
  }
  const label = document.querySelector('[data-zoom="0"]');
  if (label) label.textContent = `${Math.round(view.scale * 100)}%`;
  markOffEdge();
}

// The gap cards keep from each other. Not decoration: the lines between them run through it, and
// two cards touching leave nowhere for a line to be seen (docs/06-console.md).
const GAP = 26;

function boxOf(pin, at) {
  return {
    left: at.x,
    top: at.y,
    right: at.x + (pin.offsetWidth || CARD_WIDTH),
    bottom: at.y + (pin.offsetHeight || 120),
  };
}

function hits(one, other) {
  return !(
    one.right + GAP <= other.left ||
    one.left >= other.right + GAP ||
    one.bottom + GAP <= other.top ||
    one.top >= other.bottom + GAP
  );
}

// "Карточки на верстаке имеют коллизию и не перекрывают друг друга + всегда оставляют
// пространство между друг другом, чтобы видеть связи."
//
// Somewhere near where it was asked to go, but not on top of anything. Sweeps downwards and then
// across, which keeps a card near its intended column — a card that belongs under a question
// should stay under that question, not fly off to the right.
function freeSpot(pin, wanted) {
  const others = [...surface.querySelectorAll('.pin')]
    .filter((one) => one !== pin && placed.has(cardName(one)))
    .map((one) => boxOf(one, placed.get(cardName(one))));
  if (!others.length) return wanted;

  for (let column = 0; column < 8; column += 1) {
    const x = wanted.x + column * (CARD_WIDTH + GAP);
    for (let step = 0; step < 40; step += 1) {
      const at = { x, y: wanted.y + step * 40 };
      if (!others.some((box) => hits(boxOf(pin, at), box))) return at;
    }
  }
  return wanted;
}

// A card is placed before its content arrives — the body is fetched, or filled from the stream —
// and then it grows. So the layout is settled again once things have their real height, and only
// cards this program placed are moved: one somebody dragged somewhere stays where they put it.
let settling = 0;

function settleOverlaps() {
  clearTimeout(settling);
  settling = setTimeout(() => {
    for (const pin of surface?.querySelectorAll('.pin:not([data-moved])') || []) {
      // Not the one in somebody's hand. A press that has not yet passed the four pixels that make
      // it a drag has not set `data-moved`, and a settle landing in that window used to teleport
      // the card out from under the cursor.
      if (moving && (moving.pin === pin || moving.with?.some((one) => one.pin === pin))) continue;
      const at = placed.get(cardName(pin));
      if (!at) continue;
      const free = freeSpot(pin, at);
      if (free.x !== at.x || free.y !== at.y) place(pin, free, { avoid: false });
    }
    drawTies();
    drawRings();
    markOffEdge();
    drawMap();
    readProcess();
  }, 60);
}

function place(pin, at, { avoid = true, remember = true } = {}) {
  const known = placed.get(cardName(pin));
  const wanted = at || known || nextFreeSpot();
  // A card somebody put somewhere stays where they put it. Collision avoidance is for cards this
  // program is placing itself.
  const where = at === undefined && known ? known : avoid ? freeSpot(pin, wanted) : wanted;
  placed.set(cardName(pin), where);
  pin.style.left = `${where.x}px`;
  pin.style.top = `${where.y}px`;
  // `remember: false` is for the middle of a drag. Writing the whole layout to localStorage is
  // synchronous and it happened once per pointer event; the map above is already up to date, so
  // the only thing deferred is the disk, and it is written when the card is let go.
  if (remember) rememberLayout();
}

// Down and to the right of whatever is already there, wrapping when it runs off the bottom. Not a
// layout algorithm — just somewhere that is not on top of the last one.
function nextFreeSpot() {
  // Minus the one being placed: `place` runs after the card is in the document, so counting them
  // all would leave the first card in the second slot.
  const taken = Math.max(0, [...surface.querySelectorAll('.pin')].length - 1);
  // Across first, then down a row. A card is taller than `STEP`, so stepping only downwards put
  // each new one on top of the last.
  const across = 4;
  return {
    x: 20 + (taken % across) * (CARD_WIDTH + 24),
    y: 20 + Math.floor(taken / across) * 220 + (taken % across) * STEP,
  };
}

/* --- moving a card ---------------------------------------------------------------------------- */
// Moving a card, and four things that were wrong with it.
//
// **The grip was a thin strip.** Only `.pin-head` moved a card, and a press anywhere else on it
// did nothing at all — not even a pan, because the press was inside a card. Most of what somebody
// aims at is the card, so most attempts to move one did nothing: "не всегда получается адекватно
// перемещаться". A folded card is now a grip all over, which is how every tool of this kind
// behaves; an opened one keeps its head as the grip, because its body is text somebody reads and
// selects.
//
// **The gesture was captured on the card.** `syncBlocks` removes and rebuilds cards while an
// answer streams in, and a card removed mid-drag took the capture with it — `pointerup` then had
// nothing to fire on, `moving` stayed set, and the card followed the cursor with no button held.
// The capture goes on the canvas, which does not come and go, and the release is listened for on
// the window, which catches a mouse let go anywhere on the screen.
//
// **Every move wrote to disk.** `place` calls `rememberLayout`, which serialises the position of
// every card on the bench — synchronously, at the rate the pointer reports, which on a fast mouse
// is over a hundred times a second, with the tie and ring geometry rebuilt alongside it. That is
// the stutter. The layout is now written once, when the card is let go, and the write itself is
// held back a moment longer besides.
//
// **A card with no remembered position started from 0,0** and jumped to the corner on the first
// touch. Where it actually is on screen is a better answer than the origin.
let moving = null;

// Set when a drag ends, and read by the click that the browser sends straight after it.
let justDragged = false;

// What may be grabbed, and what is somebody trying to press or read instead.
const NOT_A_GRIP =
  'button, a, input, textarea, select, summary, details, option, label, .pin-live, .pin-role, .pin-leave';

function gripOf(target) {
  if (target.closest(NOT_A_GRIP)) return null;
  const pin = target.closest('.pin');
  if (!pin) return null;
  // A folded card is a handle all over. An opened one is text, so it keeps its head.
  if (target.closest('.pin-head')) return pin;
  return pin.dataset.view === 'hint' ? pin : null;
}

// The strip of tools, the map and the run bar float over the canvas rather than beside it, so
// every canvas gesture used to see them as bare bench: a press on a tool button began a band, the
// band's `preventDefault` then ate the click that would have chosen the tool, and the area tool
// could be entered and not left. One list, read by all three gestures — pan, band, and the click
// that clears the choice — because "is this the bench itself" is one question, and three copies of
// the answer is how the next control added here goes wrong the same way.
const FURNITURE = '.pin, .ring, #tools, #bench-map, #run-bar, #bench-menu, #chosen-bar';

function onBareBench(target) {
  return !target.closest(FURNITURE);
}

// Where a card is now, from the layout if it is known and from the page if it is not.
function whereIs(pin) {
  const at = placed.get(cardName(pin));
  if (at) return { ...at };
  return { x: pin.offsetLeft || 0, y: pin.offsetTop || 0 };
}

canvas?.addEventListener('pointerdown', (event) => {
  const pin = gripOf(event.target);
  if (event.button !== 0) return;
  if (event.target.closest(NOT_A_GRIP)) return;
  // "Вкл-выкл курсор — не перетягивает карточки, а просто их включает и выключает." A tool whose
  // whole promise is that a press does one thing has to not also do the other one.
  // Only Move moves. Every other tool's whole promise is that a press on a card does one thing,
  // and a tool that also slides the card underneath has broken it before the press is finished.
  if (tool !== 'move' && pin) return;

  if (pin) {
    const at = whereIs(pin);
    moving = {
      pin,
      from: { ...at },
      // What went out together moves together: "при запуске в обработку несколько выделенных
      // карточек как контекст — они перемещаются вместе". A ring is a group, and a group that
      // comes apart the moment somebody nudges one of its cards is a frame around nothing.
      with: alsoMoving(pin),
      startX: event.clientX,
      startY: event.clientY,
      moved: false,
    };
    // On the canvas, not on the card: a card can be rebuilt out from under a drag, and the
    // canvas cannot.
    canvas.setPointerCapture?.(event.pointerId);
    pin.classList.add('moving');
    for (const other of moving.with) other.pin.classList.add('moving');
    return;
  }

  // Empty surface, or a part of a card that is not a grip: pan. The same gesture the whole class
  // of tool uses.
  //
  // Except when the same press is about to draw a box. Both handlers are on the canvas and both
  // used to run: the surface slid away under the band while it was being drawn, so the box was
  // measured against one frame and the cards against another, and it caught nothing. A gesture
  // does one thing.
  if (onBareBench(event.target) && !(event.shiftKey || tool === 'area')) {
    moving = {
      pan: true,
      from: { x: view.x, y: view.y },
      startX: event.clientX,
      startY: event.clientY,
      moved: false,
    };
    canvas.classList.add('panning');
  }
});

canvas?.addEventListener('pointermove', (event) => {
  if (!moving) return;
  const dx = event.clientX - moving.startX;
  const dy = event.clientY - moving.startY;
  if (!moving.moved && Math.hypot(dx, dy) < 4) return; // still a click, not yet a drag
  moving.moved = true;

  if (moving.pan) {
    view.x = moving.from.x + dx;
    view.y = moving.from.y + dy;
    applyView();
    return;
  }
  place(
    moving.pin,
    {
      x: Math.round(moving.from.x + dx / view.scale),
      y: Math.round(moving.from.y + dy / view.scale),
    },
    { avoid: false, remember: false }
  );
  moving.pin.dataset.moved = 'yes';
  // The rest of the group, by the same offset — the shape of the group is what makes it one.
  for (const other of moving.with || []) {
    place(
      other.pin,
      {
        x: Math.round(other.from.x + dx / view.scale),
        y: Math.round(other.from.y + dy / view.scale),
      },
      { avoid: false, remember: false }
    );
    other.pin.dataset.moved = 'yes';
  }
  redrawSoon();
});

// The lines and the frames follow the card, but once a frame rather than once an event.
//
// A pointer reports faster than a screen refreshes, and each of these rebuilds the whole tie
// layer and measures every ringed card. Doing that per event is work thrown away between paints,
// and it is what made a drag feel like it was catching.
let redrawing = 0;

function redrawSoon() {
  if (redrawing) return;
  redrawing = requestAnimationFrame(() => {
    redrawing = 0;
    drawTies();
    drawRings();
  });
}

// The other cards that move when this one does: the rest of whatever rings hold it.
//
// Only rings. Being joined by a line is not being in a group — a line says two things are related,
// and dragging one end of a relation apart from the other is a thing somebody does on purpose. A
// ring says these went out as one question, and that is a set with an edge.
function alsoMoving(pin) {
  const name = cardName(pin);
  // A chosen card moves everything chosen with it. That is the point of choosing them, and it
  // takes precedence over the ring: somebody who has just drawn a band around six cards means
  // those six.
  if (pin.classList.contains('chosen')) {
    return chosenCards()
      .filter((other) => other !== pin && placed.get(cardName(other)))
      .map((other) => ({ pin: other, from: { ...placed.get(cardName(other)) } }));
  }
  const together = new Set();
  for (const ring of surface?.querySelectorAll('.ring') || []) {
    const holds = (ring.dataset.holds || '').split(',').filter(Boolean);
    if (!holds.includes(name)) continue;
    for (const held of holds) together.add(held);
  }
  together.delete(name);
  return [...together]
    .map((held) => ({
      pin: surface.querySelector(`.pin[data-name="${CSS.escape(held)}"]`),
      from: placed.get(held),
    }))
    .filter((one) => one.pin && one.from)
    .map((one) => ({ pin: one.pin, from: { ...one.from } }));
}

function endMove() {
  if (!moving) return;
  moving.pin?.classList.remove('moving');
  for (const other of moving.with || []) other.pin.classList.remove('moving');
  canvas?.classList.remove('panning');
  const wasAMove = moving.moved;
  const wasACard = Boolean(moving.pin);
  moving = null;
  if (wasAMove) {
    // A drag is not a click. Without this, moving a card by its head also chose it — and moving
    // cards about is what somebody does all day on a surface like this one.
    justDragged = true;
    drawTies();
    drawRings();
    // Once, here, rather than on every event of the drag. Deliberate: this is the gesture undo
    // exists for, and the only way a position gets into the history.
    if (wasACard) moveWasDeliberate();
  }
  return wasAMove;
}

// On the window, not the canvas. A mouse let go over the input field, over the browser's own
// chrome, or over a card that has since been rebuilt still ends the drag — before this, any of
// those left the card stuck to the cursor with no button held, which is the behaviour that had to
// be explained rather than the one that had to be used.
window.addEventListener('pointerup', endMove);
window.addEventListener('pointercancel', endMove);
window.addEventListener('lostpointercapture', endMove);
// And a window that loses focus mid-drag — an alt-tab — does not come back holding a card.
window.addEventListener('blur', endMove);

/* --- moving a card without a mouse ------------------------------------------------------------ */
// "На стрелочки тоже добавь перемещение."
//
// The same move, by keyboard: a card that has focus moves; with nothing focused the arrows pan the
// bench, which is the other thing arrows mean on a surface like this one. Shift makes the step a
// long one, because nudging a card across a bench twelve pixels at a time is not moving it.
//
// A card in a ring moves with its ring, exactly as it does under the pointer — one rule for what a
// group is, whichever hand moved it.
const NUDGE = 12;
const NUDGE_FAR = 96;
const ARROWS = {
  ArrowLeft: { x: -1, y: 0 },
  ArrowRight: { x: 1, y: 0 },
  ArrowUp: { x: 0, y: -1 },
  ArrowDown: { x: 0, y: 1 },
};

function nudge(pin, dx, dy) {
  const at = whereIs(pin);
  place(pin, { x: at.x + dx, y: at.y + dy }, { avoid: false });
  pin.dataset.moved = 'yes';
  for (const other of alsoMoving(pin)) {
    place(other.pin, { x: other.from.x + dx, y: other.from.y + dy }, { avoid: false });
    other.pin.dataset.moved = 'yes';
  }
  drawTies();
  drawRings();
  markOffEdge();
  moveWasDeliberate();
}

document.addEventListener('keydown', (event) => {
  if (event.target.closest('input, textarea, select, [contenteditable="true"]')) return;
  if (event.key === 'm' && !event.ctrlKey && !event.metaKey && !event.altKey) {
    document.querySelector('[data-map]')?.click();
    return;
  }
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'a' && surface?.querySelector('.pin')) {
    event.preventDefault();
    for (const pin of surface.querySelectorAll('.pin')) pin.classList.add('chosen');
    showChosen();
    return;
  }
  if (event.key === 'Escape' && tool !== 'move') {
    useTool('move');
    return;
  }
  if (event.key === 'Escape' && chosenCards().length) {
    event.preventDefault();
    event.stopPropagation();
    chooseNone();
  }
});

document.addEventListener('keydown', (event) => {
  const step = ARROWS[event.key];
  if (!step) return;
  if (event.metaKey || event.ctrlKey || event.altKey) return;
  // Somebody typing is not somebody steering, and the message field is where this page is mostly
  // used. An arrow key inside a field moves the caret and nothing else.
  if (event.target.closest('input, textarea, select, [contenteditable="true"]')) return;

  // Whatever is chosen, or failing that whatever has focus. A band somebody has just drawn is a
  // clearer statement of "these" than which card the browser last put a ring on.
  const pin = chosenCards()[0] || document.activeElement?.closest?.('.pin');
  const far = event.shiftKey ? NUDGE_FAR : NUDGE;
  event.preventDefault();
  if (pin) {
    nudge(pin, step.x * far, step.y * far);
    return;
  }
  // Nothing has focus: the arrows move the view instead. Right shows what is to the right, which
  // means the surface goes left — the direction people expect is the one the content appears from.
  view.x -= step.x * far;
  view.y -= step.y * far;
  applyView();
  markOffEdge();
});


/* --- choosing several cards at once ------------------------------------------------------------- */
// Shift and drag across the surface. Not a plain drag: that pans, which is the gesture somebody
// already has in their hands and taking it away to add this would be a bad trade.
//
// What being chosen is *for* is that every one-card action becomes an all-of-them action. On a
// bench of twelve cards the alternative is twelve presses, and twelve presses is how a bench ends
// up with cards nobody switched off because it was not worth the effort.
let band = null;

function chosenCards() {
  return [...(surface?.querySelectorAll('.pin.chosen') || [])];
}

function chooseNone() {
  for (const pin of chosenCards()) pin.classList.remove('chosen');
  showChosen();
}

function showChosen() {
  // The choice is the context, so anything that changes it changes what the next message carries.
  syncTargets();
  // And the map: on a bench too big for its window, the map is where "what is chosen" is
  // answerable at all. Redrawn here rather than only when the view moves, because the selection
  // changes far more often than the view does.
  drawMap();
  const bar = document.getElementById('chosen-bar');
  if (!bar) return;
  const many = chosenCards();
  bar.hidden = many.length < 2;
  const says = bar.querySelector('.chosen-count');
  if (says) says.textContent = `${many.length} chosen`;
}

/* --- what the pointer does -------------------------------------------------------------------- */
// "Точка вкл/выкл слишком маленькая и неприметная… давай добавим несколько иконок инструментов, как
// сделано например в графических редакторах."
//
// He is right, and the reason is not the size of the dot. A control that changes what a *click*
// means has to be visible before the click, and a mark on one card cannot say what the pointer will
// do on the next one. A tool strip says it once, for everything, and stays said.
//
// Four, because there are four things a pointer does on this surface and no more. Each is a mode
// and each stays chosen until another is — the convention every drawing program has had for thirty
// years, and people arrive already knowing it. Escape goes back to Move, which is the way out
// somebody reaches for without being told.
//
// The fourth is Combine, and it needed a mode rather than a modifier. "Перетащил одну карточку на
// другую — получил третью": on a bench where cards are dragged around all day, a plain drop onto
// another card cannot mean this, because parking one card over another is something people do by
// accident every minute. A held key would have worked and nobody would ever have found it — which
// is the argument that put this strip here in the first place.
const TOOLS = { move: 'Move', choose: 'Choose', area: 'Choose an area', mix: 'Combine' };
const TOOL_KEYS = {
  v: 'move',
  c: 'choose',
  g: 'area',
  x: 'mix',
  1: 'move',
  2: 'choose',
  3: 'area',
  4: 'mix',
};
let tool = 'move';

function useTool(name) {
  if (!TOOLS[name]) return;
  tool = name;
  for (const button of document.querySelectorAll('[data-tool]')) {
    button.setAttribute('aria-pressed', String(button.dataset.tool === name));
  }
  // The cursor is the other half of saying what will happen: a crosshair over a card is a promise
  // that clicking it will not drag it.
  canvas?.classList.toggle('choosing', name === 'choose');
  canvas?.classList.toggle('boxing', name === 'area');
  canvas?.classList.toggle('mixing', name === 'mix');
  const said = document.querySelector('.tool-said');
  // Named out loud for the moment after a press, because an icon that has just changed meaning is
  // an icon somebody wants confirmed.
  if (said) said.textContent = name === 'move' ? '' : TOOLS[name];
  // Read when it is about to matter rather than kept in a variable: the rule belongs to the chat,
  // and chats are switched between without this page reloading.
  if (name === 'mix') sayWhatCombiningAsks();
}

document.getElementById('tools')?.addEventListener('click', (event) => {
  const button = event.target.closest('[data-tool]');
  if (button) useTool(button.dataset.tool);
});

document.addEventListener('keydown', (event) => {
  if (event.metaKey || event.ctrlKey || event.altKey) return;
  // `closest` on the target, guarded: a key event can arrive with the document itself as its
  // target, and `document.closest` is not a function — which is a listener that throws on a key
  // press rather than one that ignores it.
  if (event.target?.closest?.('input, textarea, select, [contenteditable]')) return;
  const wanted = TOOL_KEYS[event.key.toLowerCase()];
  if (!wanted) return;
  event.preventDefault();
  useTool(wanted);
});

canvas?.addEventListener('pointerdown', (event) => {
  if (event.button !== 0 || !(event.shiftKey || tool === 'area')) return;
  if (!onBareBench(event.target)) return;
  event.preventDefault();
  const frame = surface.getBoundingClientRect();
  band = {
    from: { x: (event.clientX - frame.left) / view.scale, y: (event.clientY - frame.top) / view.scale },
    box: document.createElement('div'),
    // Held down: add to what is already chosen. Otherwise the box says what the question is about,
    // and what it does not touch is not part of it — the same rule as clicking a single card, which
    // has never meant "and keep the last one too". A box that only ever adds cannot take anything
    // back, so the only way out of a wrong selection would be to clear it and start over.
    adds: event.shiftKey,
  };
  band.box.className = 'band';
  surface.appendChild(band.box);
  canvas.setPointerCapture?.(event.pointerId);
});

canvas?.addEventListener('pointermove', (event) => {
  if (!band) return;
  const frame = surface.getBoundingClientRect();
  const to = {
    x: (event.clientX - frame.left) / view.scale,
    y: (event.clientY - frame.top) / view.scale,
  };
  const left = Math.min(band.from.x, to.x);
  const top = Math.min(band.from.y, to.y);
  band.box.style.left = `${left}px`;
  band.box.style.top = `${top}px`;
  band.box.style.width = `${Math.abs(to.x - band.from.x)}px`;
  band.box.style.height = `${Math.abs(to.y - band.from.y)}px`;
  band.at = { left, top, right: left + Math.abs(to.x - band.from.x), bottom: top + Math.abs(to.y - band.from.y) };
});

function endBand() {
  if (!band) return;
  const at = band.at;
  const adds = band.adds;
  band.box.remove();
  band = null;
  if (!at) return;
  if (!adds) for (const pin of surface.querySelectorAll('.pin.chosen')) pin.classList.remove('chosen');
  for (const pin of surface.querySelectorAll('.pin')) {
    const spot = placed.get(cardName(pin));
    if (!spot) continue;
    // Touching counts, not containing. A band you have to draw right around a card is a band you
    // draw twice.
    const over =
      spot.x < at.right &&
      spot.x + (pin.offsetWidth || CARD_WIDTH) > at.left &&
      spot.y < at.bottom &&
      spot.y + pin.offsetHeight > at.top;
    if (over) pin.classList.add('chosen');
  }
  showChosen();
}

// --- two cards make a third -------------------------------------------------------------------
// "Создал условно 4 карточки с элементами, а дальше за счёт интерфейса могу получать и комбинировать
// новые элементы и изделия." Ключевое слово — «за счёт интерфейса»: перетащил одну карточку на
// другую, получил третью.
//
// What comes back is an ordinary answer card, which is the whole point: the third thing can be
// combined again, and the chain does not stop at the second step. Nothing is written into the idea
// pool — this is a thing made on the bench, and whether it is worth keeping is a separate press.
//
// What it *asks* is not here. "Одна и та же пара в разных правилах даёт разное": the rule belongs
// to the workbench and the server holds it, so a drag sends two card names and nothing else
// (061-the-rule-a-combine-follows.sql). A copy of the wording in this file would be a second
// answer to "what does combining mean", and the two would part company the first time one moved.

let mixing = null;

function cardUnder(event) {
  return document.elementFromPoint(event.clientX, event.clientY)?.closest?.('.pin') || null;
}

function markToMix(pin) {
  if (mixing?.over === pin) return;
  mixing?.over?.classList.remove('to-mix');
  mixing.over = pin;
  pin?.classList.add('to-mix');
}

function stopMixing() {
  mixing?.from?.classList.remove('joining');
  mixing?.over?.classList.remove('to-mix');
  mixing = null;
}

canvas?.addEventListener('pointerdown', (event) => {
  if (event.button !== 0 || tool !== 'mix') return;
  const pin = event.target.closest('.pin');
  if (!pin) return;
  event.preventDefault();
  // Held down: ask again even though these two have already made something. Without it a pair
  // answers once and for ever, and "try it another way" would mean deleting the first answer.
  mixing = { from: pin, over: null, again: event.shiftKey };
  pin.classList.add('joining');
  canvas.setPointerCapture?.(event.pointerId);
});

canvas?.addEventListener('pointermove', (event) => {
  if (!mixing) return;
  const over = cardUnder(event);
  markToMix(over && over !== mixing.from ? over : null);
});

window.addEventListener('pointerup', (event) => {
  if (!mixing) return;
  const from = mixing.from;
  const onto = mixing.over || (cardUnder(event) !== from ? cardUnder(event) : null);
  const again = mixing.again;
  stopMixing();
  if (onto) combine(cardName(from), cardName(onto), again);
});
window.addEventListener('pointercancel', stopMixing);

// The rule, shown on the tool that follows it. A tooltip is where somebody looks to find out what
// a button does, so it is where "what will this ask" belongs — and it is read from the server, so
// what the tooltip promises and what the drag sends cannot differ.
async function sayWhatCombiningAsks() {
  const button = document.querySelector('[data-tool="mix"]');
  if (!button) return;
  try {
    const answer = await fetch(`/workbench/combining?thread=${encodeURIComponent(activeThread())}`);
    const said = await answer.json();
    button.title = `Combine — drag one card onto another and the two make a third (X). Shift for another answer from a pair that already made one\n\nIt asks: ${said.said}`;
  } catch {
    // Leave the tooltip as the markup wrote it. A control that says nothing about its rule is
    // worse than one that says it wrongly, and both are better than a page that stopped working.
  }
}

async function howCombiningWorks() {
  let now = '';
  try {
    const answer = await fetch(`/workbench/combining?thread=${encodeURIComponent(activeThread())}`);
    now = (await answer.json()).said || '';
  } catch {
    say('Could not read the rule.');
    return;
  }
  // Prefilled with what it asks now, so changing it is editing a sentence rather than writing one
  // — and clearing the box is how somebody goes back to the console's own.
  const said = window.prompt('When two cards are put together, ask this. Empty for the usual:', now);
  if (said === null) return;
  const answer = await fetch('/workbench/combining', {
    method: 'POST',
    headers: FORM,
    body: new URLSearchParams({ thread: activeThread(), said }),
  });
  const set = await answer.json();
  say(set.why || (set.its_own ? `Two cards now ask: ${set.said}` : 'Back to the usual rule.'));
  sayWhatCombiningAsks();
}

// What these two already made, or nothing. Asked before spending the call: "собрал то же самое и
// получил другое" is a world nobody can build in, and the answer somebody wants back is the card
// they already have rather than a second one beside it saying almost the same.
async function alreadyMade(from, onto) {
  try {
    const answer = await fetch(
      `/workbench/made?thread=${encodeURIComponent(activeThread())}&pair=${encodeURIComponent(`${from},${onto}`)}`
    );
    return await answer.json();
  } catch {
    // A check that failed must not stop the gesture: worst case, it is asked twice.
    return {};
  }
}

function showItAgain(id) {
  const card = surface?.querySelector(`.pin[data-name="answer:${CSS.escape(id)}"]`);
  if (!card) return false;
  bringIntoView(card);
  card.classList.add('about-this');
  setTimeout(() => card.classList.remove('about-this'), 2500);
  say('These two already made this. Hold shift and drag to ask for another.');
  return true;
}

async function combine(from, onto, again) {
  if (!again) {
    const had = await alreadyMade(from, onto);
    if (had.block && showItAgain(had.block)) return;
  }
  say(`Combining “${labelOf(from)}” and “${labelOf(onto)}”…`);
  const body = new URLSearchParams({
    thread: activeThread(),
    // No card for the question, the same as a button: what was asked is the gesture, and a card
    // repeating the gesture back is a card nobody reads twice.
    button: 'yes',
    gesture: 'combine',
    targets: [from, onto].join(','),
    // The same two cards said twice, because they are two different facts about this message.
    // `targets` is what the question is about, which every message has. `made_from` is what the
    // third card was made out of, which only a combine has — and it is what the answer card reads
    // to find its way back under the two, on this page load and on every one after it.
    made_from: [from, onto].join(','),
    history: attachedBlocks(),
    // The notes a person wrote on the bench travel with every other message, and a combine that
    // quietly left them out would be the one message that means something different.
    notes: ownBlockText(),
  });
  try {
    const answer = await fetch('/blocks', { method: 'POST', headers: { ...FORM, 'HX-Request': 'true' }, body });
    if (!answer.ok) {
      say('It did not send.');
      return;
    }
    document.getElementById('blocks').innerHTML = await answer.text();
    if (window.htmx) htmx.process(document.getElementById('blocks'));
    syncBlocks();
    showActiveThread();
  } catch {
    say('It did not send.');
  }
}

window.addEventListener('pointerup', endBand);
window.addEventListener('pointercancel', endBand);

// A press on bare surface that did not become a pan is somebody clearing the selection, which is
// what clicking away means everywhere else.
canvas?.addEventListener('click', (event) => {
  if (!onBareBench(event.target)) return;
  if (event.shiftKey) return;
  chooseNone();
});

// Shift-clicking a card adds or removes just that one, which is the other half of the gesture.
canvas?.addEventListener('click', (event) => {
  if (!event.shiftKey) return;
  const pin = event.target.closest('.pin');
  if (!pin) return;
  event.preventDefault();
  event.stopPropagation();
  pin.classList.toggle('chosen');
  showChosen();
});

// What can be done to all of them at once. Each is the one-card action, applied across — nothing
// here can do anything a single card could not.
document.getElementById('chosen-bar')?.addEventListener('click', (event) => {
  const button = event.target.closest('[data-many]');
  if (!button) return;
  const many = chosenCards();
  if (button.dataset.many === 'off') {
    for (const pin of many) pin.remove(), placed.delete(cardName(pin));
  } else if (button.dataset.many === 'out') {
    // If any of them is still in the message, the press switches them all off; otherwise it
    // switches them all back on. One button whose meaning is the state of the group.
    const anyLive = many.some((pin) => !pin.classList.contains('spent'));
    for (const pin of many) pin.classList.toggle('spent', anyLive);
  } else if (button.dataset.many === 'fold') {
    const anyOpen = many.some((pin) => pin.dataset.view !== 'hint');
    for (const pin of many) setView(pin, anyOpen ? 'hint' : 'metadata');
  } else if (button.dataset.many === 'none') {
    chooseNone();
  }
  if (button.dataset.many === 'off') chooseNone();
  syncTargets();
  drawTies();
  drawRings();
  settleOverlaps();
});


/* --- the little map ---------------------------------------------------------------------------- */
// Past a dozen cards the bench is bigger than the window, and the only way to find out what is off
// the edge was to zoom out until nothing could be read. The map is the other answer: everything at
// once, too small to read and big enough to point at.
//
// Drawn from `placed` rather than from the DOM. Those are the same coordinates the cards are laid
// out from, so the map cannot disagree with the bench — and a card that is off the edge has no
// box on screen to measure.
const mapBox = document.getElementById('bench-map');

function drawMap() {
  if (!mapBox || mapBox.hidden) return;
  const spots = [...surface.querySelectorAll('.pin')]
    .map((pin) => ({ at: placed.get(cardName(pin)), w: pin.offsetWidth || CARD_WIDTH, h: pin.offsetHeight || 120, pin }))
    .filter((one) => one.at);
  const frame = canvas.getBoundingClientRect();
  // No special case for an empty bench. Every `Math.min` below already has the viewport in it, so
  // with no cards the map draws exactly the rectangle saying where you are — which is more use
  // than an empty box, and one path through this function instead of two.
  //
  // What the map has to cover: every card, and wherever the window currently is — otherwise
  // panning off into empty space leaves the viewport rectangle outside the map that should be
  // showing it.
  const seen = {
    left: -view.x / view.scale,
    top: -view.y / view.scale,
    right: (-view.x + frame.width) / view.scale,
    bottom: (-view.y + frame.height) / view.scale,
  };
  const left = Math.min(seen.left, ...spots.map((one) => one.at.x));
  const top = Math.min(seen.top, ...spots.map((one) => one.at.y));
  const right = Math.max(seen.right, ...spots.map((one) => one.at.x + one.w));
  const bottom = Math.max(seen.bottom, ...spots.map((one) => one.at.y + one.h));
  const scale = Math.min(mapBox.clientWidth / (right - left || 1), mapBox.clientHeight / (bottom - top || 1));
  mapBox.dataset.left = String(left);
  mapBox.dataset.top = String(top);
  mapBox.dataset.scale = String(scale);

  const made = [];
  for (const one of spots) {
    const dot = document.createElement('span');
    dot.className = `map-dot${one.pin.classList.contains('spent') ? ' spent' : ''}` +
      `${one.pin.classList.contains('chosen') ? ' chosen' : ''}`;
    dot.style.left = `${(one.at.x - left) * scale}px`;
    dot.style.top = `${(one.at.y - top) * scale}px`;
    dot.style.width = `${Math.max(2, one.w * scale)}px`;
    dot.style.height = `${Math.max(2, one.h * scale)}px`;
    made.push(dot);
  }
  const here = document.createElement('span');
  here.className = 'map-here';
  here.style.left = `${(seen.left - left) * scale}px`;
  here.style.top = `${(seen.top - top) * scale}px`;
  here.style.width = `${(seen.right - seen.left) * scale}px`;
  here.style.height = `${(seen.bottom - seen.top) * scale}px`;
  made.push(here);
  mapBox.replaceChildren(...made);
}

// Press the map to go there. The window centres on the point pressed, which is the one thing a
// map like this is for.
mapBox?.addEventListener('pointerdown', (event) => {
  const scale = Number(mapBox.dataset.scale) || 1;
  const box = mapBox.getBoundingClientRect();
  const frame = canvas.getBoundingClientRect();
  const at = {
    x: Number(mapBox.dataset.left) + (event.clientX - box.left) / scale,
    y: Number(mapBox.dataset.top) + (event.clientY - box.top) / scale,
  };
  view.x = frame.width / 2 - at.x * view.scale;
  view.y = frame.height / 2 - at.y * view.scale;
  applyView();
  drawMap();
});

document.querySelector('[data-map]')?.addEventListener('click', () => {
  if (!mapBox) return;
  mapBox.hidden = !mapBox.hidden;
  try {
    localStorage.setItem('agent-desk:bench-map', mapBox.hidden ? 'no' : 'yes');
  } catch {
    // A window that will not remember still shows it.
  }
  drawMap();
});

try {
  if (mapBox && localStorage.getItem('agent-desk:bench-map') === 'yes') mapBox.hidden = false;
} catch {
  // Nothing remembered is the same as never having asked for it.
}

/* --- benches you can come back to -------------------------------------------------------------- */
// A set of cards gathered for one piece of work is gathered by hand every time. Saving it under a
// name is the difference between a surface and a desk you can leave things on.
//
// In this browser, beside the column widths and the tab order, and for the same reason: a layout
// says nothing about the ideas or the sessions themselves — it is where *this person* likes them.
const BENCHES = 'agent-desk:benches';

function savedBenches() {
  try {
    return JSON.parse(localStorage.getItem(BENCHES) || '{}');
  } catch {
    return {};
  }
}

function benchNow() {
  return [...surface.querySelectorAll('.pin[data-kind]:not(.copy):not(.collection)')]
    .map((pin) => ({
      kind: pin.dataset.kind,
      id: pin.dataset.id,
      label: pin.querySelector('.pin-label')?.textContent?.trim() || '',
      at: placed.get(cardName(pin)) || null,
      spent: pin.classList.contains('spent'),
      view: pin.dataset.view || 'hint',
    }))
    .filter((one) => one.at && one.kind !== 'block' && one.kind !== 'note');
}

function keepBench() {
  const cards = benchNow();
  if (!cards.length) return say('There is nothing on the workbench to save.');
  const name = prompt('Save this workbench as:', '')?.trim();
  if (!name) return;
  const all = savedBenches();
  all[name] = cards;
  try {
    localStorage.setItem(BENCHES, JSON.stringify(all));
  } catch {
    return say('This browser would not keep it.');
  }
  say(`Saved “${name}” — ${cards.length} card${cards.length === 1 ? '' : 's'}.`);
}

async function openBench(name) {
  const cards = savedBenches()[name];
  if (!cards) return;
  clearBench();
  for (const one of cards) {
    await pin(
      { kind: one.kind, id: one.id, label: one.label },
      { at: one.at, quiet: true, exact: true, came: `from the saved workbench “${name}”` }
    );
    const node = surface.querySelector(`.pin[data-name="${CSS.escape(`${one.kind}:${one.id}`)}"]`);
    if (!node) continue;
    node.classList.toggle('spent', !!one.spent);
    setView(node, one.view);
  }
  syncTargets();
  drawTies();
  drawMap();
}

function forgetBench(name) {
  const all = savedBenches();
  delete all[name];
  try {
    localStorage.setItem(BENCHES, JSON.stringify(all));
  } catch {
    // Nothing to do about a browser that will not write.
  }
  showBenches();
}

// The list, rebuilt from what is saved. A menu that has to be kept in step by hand is a menu that
// offers a bench somebody deleted.
function showBenches() {
  const into = document.getElementById('bench-saved');
  if (!into) return;
  const names = Object.keys(savedBenches()).sort();
  into.replaceChildren();
  if (!names.length) {
    const none = document.createElement('li');
    none.className = 'saved-none';
    none.textContent = 'nothing saved yet';
    into.appendChild(none);
    return;
  }
  for (const name of names) {
    const row = document.createElement('li');
    const open = document.createElement('button');
    open.type = 'button';
    open.className = 'saved-open';
    open.textContent = name;
    open.addEventListener('click', () => {
      hideMenu();
      openBench(name);
    });
    const drop = document.createElement('button');
    drop.type = 'button';
    drop.className = 'saved-drop';
    drop.textContent = '×';
    drop.title = `forget ${name}`;
    drop.addEventListener('click', (event) => {
      event.stopPropagation();
      forgetBench(name);
    });
    row.append(open, drop);
    into.appendChild(row);
  }
}

function say(words) {
  const where = document.getElementById('context-count');
  if (!where) return;
  where.textContent = words;
  setTimeout(syncTargets, 4000);
}


/* --- what a card is in a process --------------------------------------------------------------- */
// Object, Action, Decision, Event, Result. The vocabulary the first user's feedback asked for, and
// the one everything after it rests on: without a role, a line between two cards says only "these
// are related"; with one, "Decision → Action" reads as a branch and "Event → Action" as a trigger.
//
// A role is not a kind. A card's kind says where it is read from and cannot change — an idea does
// not become a session. Its role is what it is doing in the process being described, and it
// changes as the description does: "карточка может менять тип по ходу процесса".
//
// Fetched rather than copied here. The five live in agent_desk/roles.py, and a list of them
// written into this file would be a second place for them to be wrong.
let roleSays = {};
let roleNaturally = {};
let roleChosen = {};
let roleFilled = {};

async function readRoles() {
  try {
    const answer = await fetch('/cards/roles');
    if (!answer.ok) return;
    const said = await answer.json();
    roleSays = said.says || {};
    roleNaturally = said.naturally || {};
    roleChosen = said.roles || {};
    roleFilled = said.fields || {};
    for (const pin of surface?.querySelectorAll('.pin') || []) showRole(pin);
  } catch {
    // A console that cannot reach itself still shows the cards; they simply have no shapes.
  }
}

function roleOf(pin) {
  const name = cardName(pin);
  const chosen = roleChosen[name];
  if (chosen && roleSays[chosen]) return chosen;
  return roleNaturally[pin.dataset.kind] || 'object';
}

function showRole(pin) {
  const role = roleOf(pin);
  pin.dataset.role = role;
  pin.dataset.shape = roleSays[role]?.shape || 'box';
  const chip = pin.querySelector('.pin-role');
  if (chip) {
    chip.textContent = roleSays[role]?.says || role;
    chip.title = `${roleSays[role]?.means || ''} — press to change what this is`;
  }
  showFields(pin);
  showLeave(pin);
}

// The small fixed set of things this role is asked (agent_desk/roles.py).
//
// Drawn here rather than in the card templates, and that is the point rather than a shortcut: any
// card can have any role, so a form that lived in the session template would have to be copied
// into the idea template, the blocker template and the folder template — four copies of one
// question, three of which would fall behind.
//
// Rebuilt only when the role changes. Redrawing it on every pass would take the caret out of an
// input somebody is typing in, which is the worst failure a form on a live-updating page has.
function showFields(pin) {
  const role = roleOf(pin);
  const asked = roleSays[role]?.fields || [];
  const body = pin.querySelector('.pin-body');
  if (!body) return;
  let form = pin.querySelector('.pin-fields');
  if (!asked.length) {
    form?.remove();
    return;
  }
  if (form && form.dataset.role === role) {
    markUnfilled(pin, form);
    return;
  }
  form?.remove();
  form = document.createElement('div');
  form.className = 'pin-fields';
  form.dataset.role = role;
  const said = roleFilled[cardName(pin)] || {};
  for (const field of asked) {
    const row = document.createElement('label');
    row.className = `pin-field${field.needed ? ' needed' : ''}`;
    const says = document.createElement('span');
    says.className = 'field-says';
    says.textContent = field.says;
    const box = document.createElement('textarea');
    box.rows = field.lines || 1;
    box.placeholder = field.asks;
    box.value = said[field.name] || '';
    box.dataset.field = field.name;
    box.addEventListener('change', () => keepField(pin, field.name, box.value));
    // Leaving the card counts as finishing the sentence. Without this, a value typed and then
    // clicked away from is a value the engine never sees.
    box.addEventListener('blur', () => keepField(pin, field.name, box.value));
    row.append(says, box);
    form.appendChild(row);
  }
  body.prepend(form);
  markUnfilled(pin, form);
  sayWhatItDoes(pin);
}

// What a folded step says about itself: the thing it does.
//
// Without this every card drawn from a template read "A step in a process. What it is and what it
// does are on the card itself" — six cards, one sentence, no information, because `writeHint`
// takes the first sentence in the body and for a step card that was boilerplate. A card's own
// answer to the question its role asks is the only sentence worth showing.
function sayWhatItDoes(pin) {
  const asked = roleSays[roleOf(pin)]?.fields || [];
  const said = roleFilled[cardName(pin)] || {};
  const words = asked
    .map((field) => (said[field.name] || '').trim())
    .find((one) => one.length > 2);
  if (!words) return;
  let line = pin.querySelector('.pin-hint');
  if (!line) {
    line = document.createElement('p');
    line.className = 'pin-hint';
    pin.querySelector('.pin-head')?.after(line);
  }
  line.textContent = words;
  line.title = words;
}

// What an engine would stop on, shown before it does. Not a refusal: half-drawn is the normal
// state of a diagram somebody is thinking in.
function markUnfilled(pin, form) {
  const said = roleFilled[cardName(pin)] || {};
  const asked = roleSays[roleOf(pin)]?.fields || [];
  const short = asked.filter((field) => field.needed && !(said[field.name] || '').trim());
  pin.classList.toggle('unfilled', short.length > 0);
  for (const row of form.querySelectorAll('.pin-field.needed')) {
    const box = row.querySelector('textarea');
    row.classList.toggle('empty', !(box?.value || '').trim());
  }
}

async function keepField(pin, field, value) {
  const name = cardName(pin);
  const said = (roleFilled[name] = roleFilled[name] || {});
  if (said[field] === value) return;
  said[field] = value;
  const form = pin.querySelector('.pin-fields');
  if (form) markUnfilled(pin, form);
  sayWhatItDoes(pin);
  try {
    await fetch('/cards/field', {
      method: 'POST',
      headers: FORM,
      body: new URLSearchParams({ name, role: roleOf(pin), field, value }),
    });
  } catch {
    // It is right on this page for this session; the next load reads what was stored.
  }
}

async function chooseRole(pin, role) {
  const name = cardName(pin);
  // On the page first: the shape changes under the hand that pressed it, and a round trip before
  // anything moves is how a control starts feeling broken.
  if (role) roleChosen[name] = role;
  else delete roleChosen[name];
  showRole(pin);
  drawTies();
  try {
    await fetch('/cards/role', {
      method: 'POST',
      headers: { 'content-type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({ name, role }),
    });
  } catch {
    // It is still right on this page for this session; the next load reads what was stored.
  }
}

// The five, offered where the card is. Not a select: five options with a shape each is a thing
// somebody points at, and a dropdown would hide exactly the information that makes them worth
// having.
function showRoleMenu(pin, x, y) {
  document.getElementById('role-menu')?.remove();
  const menu = document.createElement('menu');
  menu.id = 'role-menu';
  menu.className = 'role-menu';
  const now = roleOf(pin);
  for (const [name, one] of Object.entries(roleSays)) {
    const row = document.createElement('li');
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `role-pick${name === now ? ' at' : ''}`;
    button.dataset.shape = one.shape;
    button.innerHTML = '<span class="role-mark" aria-hidden="true"></span>' +
      '<span class="role-says"></span><span class="role-means"></span>';
    button.querySelector('.role-says').textContent = one.says;
    button.querySelector('.role-means').textContent = one.means;
    button.addEventListener('click', () => {
      menu.remove();
      chooseRole(pin, name);
    });
    row.appendChild(button);
    menu.appendChild(row);
  }
  const back = document.createElement('li');
  const plain = document.createElement('button');
  plain.type = 'button';
  plain.className = 'role-pick plain';
  plain.textContent = 'whatever it naturally is';
  plain.addEventListener('click', () => {
    menu.remove();
    chooseRole(pin, '');
  });
  back.appendChild(plain);
  menu.appendChild(back);
  document.body.appendChild(menu);
  menu.style.left = `${Math.min(x, window.innerWidth - menu.offsetWidth - 8)}px`;
  menu.style.top = `${Math.min(y, window.innerHeight - menu.offsetHeight - 8)}px`;
}

document.addEventListener('click', (event) => {
  const chip = event.target.closest('.pin-role');
  if (!chip) {
    if (!event.target.closest('#role-menu')) document.getElementById('role-menu')?.remove();
    return;
  }
  event.preventDefault();
  event.stopPropagation();
  const box = chip.getBoundingClientRect();
  showRoleMenu(chip.closest('.pin'), box.left, box.bottom + 4);
});

readRoles();


/* --- lines that say what happens --------------------------------------------------------------- */
// then · if · when · makes · with (agent_desk/ties.py).
//
// A line that says only "these two are related" is a picture: read a bench of them and you learn
// that somebody thought six things belong together, which you already knew, because they are on
// the same bench. A line that says **then**, **if**, **when** is a sentence — it can be read top
// to bottom by somebody who was not there.
//
// The kind is *suggested* from the roles at both ends and never enforced. Somebody sketching is
// thinking, and a constructor that rejects the line you drew because the boxes are not yet the
// right shape is a constructor you fight.
let tieKinds = {};
let tieFromRole = {};
let tieIntoRole = {};
let tieOrdinarily = 'then';
let drawnTies = [];

async function readLines() {
  try {
    const answer = await fetch('/workbench/lines');
    if (!answer.ok) return;
    const said = await answer.json();
    tieKinds = said.kinds || {};
    tieFromRole = said.from_role || {};
    tieIntoRole = said.into_role || {};
    tieOrdinarily = said.ordinarily || 'then';
    drawnTies = said.lines || [];
    drawTies();
  } catch {
    // A console that cannot reach itself still shows the cards.
  }
}

// Which of the five a line between these two probably is. The same rule as `ties.natural`, asked
// of the server's own answer rather than reimplemented: what a line is is decided by what it
// comes out of.
function naturalTie(fromPin, toPin) {
  const out = fromPin ? roleOf(fromPin) : '';
  const into = toPin ? roleOf(toPin) : '';
  return tieFromRole[out] || tieIntoRole[into] || tieOrdinarily;
}

// Only the lines with both ends on the bench. A line to something you cannot see explains nothing,
// which is the rule the idea map has always followed.
function processTies() {
  return drawnTies
    .filter((line) => showing(line.from) && showing(line.to))
    .map((line) => ({
      from: line.from,
      to: line.to,
      says: line.says || tieKinds[line.kind]?.says || line.kind,
      kind: line.kind,
      id: line.id,
      drawn: true,
    }));
}

async function drawLine(from, to, kind, says = '') {
  const body = new URLSearchParams({ from, to, kind, says, thread: activeThread() });
  // On the page first, so the line appears under the hand that drew it.
  drawnTies = drawnTies.filter((line) => !(line.from === from && line.to === to));
  drawnTies.push({ id: `new-${from}-${to}`, from, to, kind, says });
  drawTies();
  try {
    await fetch('/workbench/tie', { method: 'POST', headers: FORM, body });
    await readLines();
  } catch {
    // It is drawn here for this session; the next load reads what was stored.
  }
}

async function rubOutLine(id) {
  drawnTies = drawnTies.filter((line) => line.id !== id);
  drawTies();
  try {
    await fetch('/workbench/untie', { method: 'POST', headers: FORM, body: new URLSearchParams({ id, thread: activeThread() }) });
  } catch {
    // Gone from this page either way.
  }
}

const FORM = { 'content-type': 'application/x-www-form-urlencoded' };

// What a line is, changed after it is drawn — and the words on it, which only a branch really
// needs: "if" with no condition is a fork nobody can follow.
function showLineMenu(line, x, y) {
  document.getElementById('role-menu')?.remove();
  const menu = document.createElement('menu');
  menu.id = 'role-menu';
  menu.className = 'role-menu';
  for (const [name, one] of Object.entries(tieKinds)) {
    const row = document.createElement('li');
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `role-pick${name === line.kind ? ' at' : ''}`;
    button.innerHTML = '<span class="role-says"></span><span class="role-means"></span>';
    button.querySelector('.role-says').textContent = one.says;
    button.querySelector('.role-means').textContent = one.means;
    button.addEventListener('click', async () => {
      menu.remove();
      // A branch is asked for its condition then and there. Anywhere else and it is a field
      // somebody fills in later, which means never.
      const words = one.wants_words
        ? (prompt('When does it go this way?', line.says === one.says ? '' : line.says) || '').trim()
        : '';
      await drawLine(line.from, line.to, name, words);
    });
    row.appendChild(button);
    menu.appendChild(row);
  }
  const off = document.createElement('li');
  const rub = document.createElement('button');
  rub.type = 'button';
  rub.className = 'role-pick plain';
  rub.textContent = 'rub the line out';
  rub.addEventListener('click', () => {
    menu.remove();
    rubOutLine(line.id);
  });
  off.appendChild(rub);
  menu.appendChild(off);
  document.body.appendChild(menu);
  menu.style.left = `${Math.min(x, window.innerWidth - menu.offsetWidth - 8)}px`;
  menu.style.top = `${Math.min(y, window.innerHeight - menu.offsetHeight - 8)}px`;
}

readLines();


/* --- the bench read as a process ---------------------------------------------------------------- */
// What order these run in, what each step would be told, and what each is allowed to do.
//
// All of it comes out of `agent_desk/process.py`, which is pure — so what this panel says and what
// a run would actually do cannot drift apart. The alternative, working the order out here as well,
// is two implementations of "what happens first" and one of them wrong.
let processSaid = {};

async function readProcess() {
  const panel = document.getElementById('process-panel');
  if (!panel || panel.hidden) return;
  const names = onBench().map(cardName);
  if (!names.length) {
    panel.querySelector('.process-body').textContent = 'Nothing on the workbench yet.';
    return;
  }
  try {
    const answer = await fetch(`/workbench/process?cards=${encodeURIComponent(names.join(','))}`);
    if (!answer.ok) return;
    processSaid = await answer.json();
    showProcess();
  } catch {
    // The bench still works; it simply cannot be read as a process right now.
  }
}

function showProcess() {
  const panel = document.getElementById('process-panel');
  const into = panel?.querySelector('.process-body');
  if (!into) return;
  into.replaceChildren();

  const why = processSaid.why_not;
  const head = document.createElement('p');
  head.className = why ? 'process-why' : 'process-ready';
  head.textContent = why || 'This can be run: every step has said what it needs.';
  into.appendChild(head);

  const list = document.createElement('ol');
  list.className = 'process-order';
  for (const name of processSaid.order || []) {
    const pin = surface.querySelector(`.pin[data-name="${CSS.escape(name)}"]`);
    const row = document.createElement('li');
    const short = (processSaid.unfinished || {})[name];
    row.className = short ? 'unfinished' : '';
    const says = document.createElement('span');
    says.className = 'process-name';
    says.textContent = pin?.querySelector('.pin-label')?.textContent?.trim() || name;
    const role = document.createElement('span');
    role.className = 'process-role';
    role.textContent = roleSays[pin ? roleOf(pin) : '']?.says || '';
    row.append(role, says);
    if (short) {
      const gap = document.createElement('span');
      gap.className = 'process-gap';
      gap.textContent = `wants ${short.join(', ')}`;
      row.appendChild(gap);
    }
    // Pressing a step shows what it would be told — which is the question "память процесса"
    // exists to answer, and the one nobody can check by looking at the boxes.
    row.addEventListener('click', () => showMemory(name));
    list.appendChild(row);
  }
  into.appendChild(list);

  for (const name of processSaid.tangled || []) {
    const loop = document.createElement('p');
    loop.className = 'process-loop';
    loop.textContent = `${name} is in a loop`;
    into.appendChild(loop);
  }
}

// What one step gets told about what leads into it.
function showMemory(name) {
  const said = (processSaid.memory || {})[name];
  const into = document.getElementById('process-panel')?.querySelector('.process-memory');
  if (!into) return;
  into.textContent = said || 'Nothing leads into this step, so it starts from what it says itself.';
}

document.querySelector('[data-process]')?.addEventListener('click', () => {
  const panel = document.getElementById('process-panel');
  if (!panel) return;
  panel.hidden = !panel.hidden;
  readProcess();
});

/* --- what one step is allowed to do ------------------------------------------------------------- */
// "Что отличает конструктор, которому можно доверить запуск, от схемы, которую страшно нажать."
//
// And the thing that makes it worth trusting: each switch says whether this console *enforces* it
// or only asks. A row of switches that look alike but do not work alike would be worse than none.
function showLeaveMenu(pin, x, y) {
  document.getElementById('role-menu')?.remove();
  const name = cardName(pin);
  const now = new Set((processSaid.leave || {})[name] || []);
  const menu = document.createElement('menu');
  menu.id = 'role-menu';
  menu.className = 'role-menu wide';
  // A step whose work is a prompt may only read, and that is what it is rather than how it is
  // set. Saying so and showing no switches beats showing switches that would be ignored — a
  // control that can be moved and then disregarded is a promise the console does not keep.
  if ((processSaid.fixed || []).includes(name)) {
    const said = document.createElement('li');
    said.className = 'leave-fixed';
    said.textContent =
      'This step sends a prompt, so it may only read: no worktree, no branch, no gate, no push. ' +
      'That is what the step is, not a setting on it.';
    menu.appendChild(said);
    document.body.appendChild(menu);
    menu.style.left = `${Math.min(x, window.innerWidth - menu.offsetWidth - 8)}px`;
    menu.style.top = `${Math.min(y, window.innerHeight - menu.offsetHeight - 8)}px`;
    return;
  }
  for (const [key, one] of Object.entries(processSaid.allowed || {})) {
    const row = document.createElement('li');
    const button = document.createElement('button');
    button.type = 'button';
    button.className = `role-pick${now.has(key) ? ' at' : ''}`;
    button.innerHTML =
      '<span class="leave-tick"></span><span class="role-says"></span>' +
      '<span class="role-means"></span><span class="leave-held"></span>';
    button.querySelector('.leave-tick').textContent = now.has(key) ? '✓' : '';
    button.querySelector('.role-says').textContent = one.says;
    button.querySelector('.role-means').textContent = one.means;
    const held = button.querySelector('.leave-held');
    held.textContent = one.held === 'enforced' ? 'held' : 'asked only';
    held.className = `leave-held ${one.held}`;
    button.title = one.how;
    button.addEventListener('click', async () => {
      if (now.has(key)) now.delete(key);
      else now.add(key);
      await keepLeave(name, [...now]);
      menu.remove();
    });
    row.appendChild(button);
    menu.appendChild(row);
  }
  document.body.appendChild(menu);
  menu.style.left = `${Math.min(x, window.innerWidth - menu.offsetWidth - 8)}px`;
  menu.style.top = `${Math.min(y, window.innerHeight - menu.offsetHeight - 8)}px`;
}

async function keepLeave(name, given) {
  processSaid.leave = processSaid.leave || {};
  processSaid.leave[name] = given;
  try {
    await fetch('/cards/leave', {
      method: 'POST',
      headers: FORM,
      body: new URLSearchParams({ name, leave: given.join(',') }),
    });
  } catch {
    // Right on this page for this session; the next read gets what was stored.
  }
  for (const pin of surface.querySelectorAll('.pin')) showLeave(pin);
}

// The chip on a step, saying how far it is allowed to go. Only on the roles that are steps: an
// Object does not do anything, so a permission on it would be a control with nothing behind it.
function showLeave(pin) {
  let chip = pin.querySelector('.pin-leave');
  if (!isAStep(pin)) {
    chip?.remove();
    return;
  }
  if (!chip) {
    chip = document.createElement('button');
    chip.type = 'button';
    chip.className = 'pin-leave';
    pin.querySelector('.pin-role')?.after(chip);
  }
  const given = (processSaid.leave || {})[cardName(pin)] || ['work'];
  // Only when it is *not* the ordinary one. Every step working in its own copy is the default, and
  // saying so on every card was six identical chips telling nobody anything — on a head so full of
  // labels that the card's own name had been squeezed out of it. A step that may merge, or that
  // may only read, is worth a word.
  chip.hidden = given.length === 1 && given[0] === 'work';
  chip.textContent = given.map((one) => processSaid.allowed?.[one]?.says || one).join(' · ');
  chip.title = 'what this step is allowed to do — press to change';
}

document.addEventListener('click', (event) => {
  const chip = event.target.closest('.pin-leave');
  if (!chip) return;
  event.preventDefault();
  event.stopPropagation();
  const box = chip.getBoundingClientRect();
  showLeaveMenu(chip.closest('.pin'), box.left, box.bottom + 4);
});


/* --- running a drawing --------------------------------------------------------------------------- */
// "Ход исполнения виден на самой схеме: где сейчас, что прошло, что упало." The run is drawn on
// the cards themselves rather than only in a list, because the drawing is the thing somebody made
// and a second representation of it beside the first is two things to keep in your head.
let runs = [];

async function readRuns() {
  try {
    const answer = await fetch('/workbench/runs');
    if (!answer.ok) return;
    runs = (await answer.json()).runs || [];
    showRuns();
  } catch {
    // The bench still works; it simply cannot say what is running.
  }
}

function showRuns() {
  const states = new Map();
  let going = null;
  for (const one of runs) {
    if (one.going) going = one;
    for (const step of one.steps) states.set(step.name, step);
  }
  for (const pin of surface?.querySelectorAll('.pin') || []) {
    const step = states.get(cardName(pin));
    pin.dataset.step = step ? step.state : '';
    pin.classList.toggle('at-now', Boolean(going && going.at === cardName(pin)));
    let mark = pin.querySelector('.pin-step');
    if (!step) {
      mark?.remove();
      continue;
    }
    if (!mark) {
      mark = document.createElement('span');
      mark.className = 'pin-step';
      pin.querySelector('.pin-role')?.before(mark);
    }
    mark.textContent = STEP_MARK[step.state] || '';
    mark.title = step.detail || step.made || step.state;
    // Only on a card that produced several answers. Decided from the run this page already has,
    // rather than by asking per card: a request every two seconds for a control most cards will
    // never show is a request nobody asked for (01M1XA1V906B3KRJ84G4KHRE33).
    const answers = pin.querySelector('.pin-answers');
    if (answers) answers.hidden = ((step.made || '').match(/^## /gm) || []).length < 2;
    writeCost(pin, step);
  }
  showRunBar(going);
  showCompare();
}

// "Промпт, который лучше на 3% и дороже вдвое, — это плохой промпт, и увидеть это надо на схеме,
// а не в счёте в конце месяца." So it is on the card, next to what the step produced.
//
// Zero is not shown, and that is the honest reading rather than tidiness: nothing was measured.
// An agent's work is not priced here, and a step that ran before this existed has no number — a
// line saying "$0.00" would be this console claiming a step was free (058-what-a-step-cost.sql).
function writeCost(pin, step) {
  let line = pin.querySelector('.pin-cost');
  const said = [];
  if (step.usd) said.push(`$${step.usd < 0.01 ? step.usd.toFixed(4) : step.usd.toFixed(2)}`);
  if (step.ms) said.push(step.ms < 1000 ? `${step.ms}ms` : `${(step.ms / 1000).toFixed(1)}s`);
  if (!said.length) {
    line?.remove();
    return;
  }
  if (!line) {
    line = document.createElement('p');
    line.className = 'pin-cost';
    pin.querySelector('.pin-head')?.after(line);
  }
  line.textContent = said.join(' · ');
}

const STEP_MARK = { waiting: '·', going: '◐', held: '⏸', done: '✓', failed: '✕' };

// "Тестировать пайплайн — значит запускать его несколько раз и смотреть, что изменилось."
//
// The history was always there — every run keeps what each of its steps produced — and nothing
// showed it. This is the two most recent runs of what is on the bench, side by side.
//
// Offered only when there are two, because comparing one run with nothing is a table of one
// column, and a control that produces one is a control somebody presses once.
function runsOfThisBench() {
  const here = new Set(onBench().map(cardName));
  return runs.filter((one) => (one.cards || []).some((name) => here.has(name)));
}

function showCompare() {
  const button = document.getElementById('compare-runs');
  if (button) button.hidden = runsOfThisBench().length < 2;
  // The spread wants two runs as well: one run has no spread, and a table of one column is what a
  // person presses once and never again.
  const spread = document.getElementById('spread-runs');
  if (spread) spread.hidden = runsOfThisBench().length < 2;
  // Repeating is offered only for a drawing of prompts, which is the same rule the route holds —
  // ten runs of a drawing with work in it is ten agents in ten worktrees.
  const again = document.getElementById('repeat-runs');
  if (again) {
    const steps = onBench().filter(isAStep);
    again.hidden =
      !steps.length || steps.some((pin) => !(processSaid.fixed || []).includes(cardName(pin)));
  }
}

async function compareTheLastTwo() {
  const mine = runsOfThisBench().slice(0, 2);
  if (mine.length < 2) return;
  // Older first, so "before" is before. `/workbench/runs` answers newest first.
  const wanted = [mine[1].id, mine[0].id].join(',');
  await showComparison(`/workbench/compare?runs=${encodeURIComponent(wanted)}`);
}

// "Два ответа, показанные друг под другом с отличиями — это то, ради чего собирают такую схему."
//
// The same panel and the same rows as two runs compared, because it is the same question asked of
// different things: here are two texts, what is different about them. A second panel would be a
// second answer to "how is a difference shown", and the two would drift.
async function showAnswersOn(holder) {
  await showComparison(`/workbench/answers?name=${encodeURIComponent(cardName(holder))}`);
}

// "Прогон N раз с показом разброса и доли прошедших проверок" — and the same control for a set of
// examples, because running twenty times with one input and once per line of twenty are the same
// act with a different list (agent_desk/spread.py).
async function repeatIt() {
  const said = (
    prompt(
      'Run it how many times? Or paste one input per line to run it once per line.',
      '5'
    ) || ''
  ).trim();
  if (!said) return;
  const lines = said.split('\n').filter((one) => one.trim());
  const body = new URLSearchParams({ cards: onBench().map(cardName).join(',') });
  if (lines.length > 1 || Number.isNaN(Number(said))) body.set('each', said);
  else body.set('times', said);
  try {
    const answer = await fetch('/workbench/repeat', {
      method: 'POST',
      headers: FORM,
      body,
    });
    const back = await answer.json();
    say(back.started ? `Started ${back.started}.` : back.why || 'Nothing was started.');
    readRuns();
  } catch {
    say('Nothing was started.');
  }
}

async function showSpread() {
  await showComparison(
    `/workbench/spread?cards=${encodeURIComponent(onBench().map(cardName).join(','))}`
  );
}

document.getElementById('repeat-runs')?.addEventListener('click', repeatIt);
document.getElementById('spread-runs')?.addEventListener('click', showSpread);

async function showComparison(where) {
  const panel = document.getElementById('compare-panel');
  if (!panel) return;
  try {
    const said = await (await fetch(where)).json();
    panel.querySelector('.compare-said').textContent = said.said || '';
    const list = panel.querySelector('.compare-rows');
    list.replaceChildren();
    for (const row of said.rows || []) {
      const item = document.createElement('li');
      item.className = row.changed ? 'compare-row changed' : 'compare-row';
      item.innerHTML =
        '<span class="compare-step"></span><span class="compare-says"></span>' +
        '<pre class="compare-before"></pre><pre class="compare-after"></pre>';
      item.querySelector('.compare-step').textContent = row.label;
      item.querySelector('.compare-says').textContent = row.says;
      // The words that changed, marked. `textContent` on every piece: these are two answers a
      // model wrote, and a model writes angle brackets.
      writeMarks(item.querySelector('.compare-before'), row.marks, 'before', row.before);
      writeMarks(item.querySelector('.compare-after'), row.marks, 'after', row.after);
      list.appendChild(item);
    }
    panel.hidden = false;
  } catch {
    say('Could not compare those.');
  }
}

// One side of a comparison: everything that is in it, with the pieces that are only in it marked.
function writeMarks(into, marks, side, whole) {
  if (!marks || !marks.length) {
    into.textContent = whole || '';
    return;
  }
  into.replaceChildren();
  for (const one of marks) {
    if (one.mark !== 'same' && one.mark !== side) continue;
    const piece = document.createElement('span');
    piece.className = one.mark === 'same' ? 'same' : 'only';
    piece.textContent = one.text;
    into.appendChild(piece);
  }
}

document.getElementById('compare-runs')?.addEventListener('click', compareTheLastTwo);
document
  .querySelector('[data-compare-off]')
  ?.addEventListener('click', () => {
    document.getElementById('compare-panel').hidden = true;
  });

function showRunBar(going) {
  const bar = document.getElementById('run-bar');
  if (!bar) return;
  bar.hidden = !going;
  if (!going) return;
  const at = surface?.querySelector(`.pin[data-name="${CSS.escape(going.at || '')}"]`);
  const held = going.steps.find((step) => step.state === 'held');
  const broke = going.steps.find((step) => step.state === 'failed');
  // Three things this bar can be saying, and they are read differently: it is working, it is
  // waiting for somebody, or it stopped and is holding its place (047-a-run-can-wait.sql).
  bar.querySelector('.run-where').textContent = going.waiting
    ? 'set aside — it kept its place'
    : broke
      ? `stopped at ${labelOf(broke.name)}: ${broke.detail}`
      : held
        ? `waiting: ${held.detail}`
        : `at ${at?.querySelector('.pin-label')?.textContent?.trim() || going.at || 'the start'}`;
  const happened = bar.querySelector('[data-happened]');
  happened.hidden = !held;
  happened.dataset.run = going.id;
  happened.dataset.name = held ? held.name : '';
  for (const [what, when] of [
    ['[data-pause]', going.going],
    ['[data-carry-on]', going.canCarryOn],
    ['[data-stop]', going.going || going.waiting],
  ]) {
    const button = bar.querySelector(what);
    button.hidden = !when;
    button.dataset.run = going.id;
  }
}

document.getElementById('run-bar')?.addEventListener('click', async (event) => {
  const button = event.target.closest('button');
  if (!button) return;
  const body = new URLSearchParams({ run: button.dataset.run || '' });
  if (button.dataset.happened !== undefined) body.set('name', button.dataset.name || '');
  // Which button, by the attribute it carries. A chain of ternaries would have to be read to add
  // the fourth; this is a row per button and the template names them the same way.
  const where = [
    ['stop', '/workbench/stop'],
    ['pause', '/workbench/pause'],
    ['carryOn', '/workbench/carry-on'],
  ].find(([which]) => button.dataset[which] !== undefined);
  await fetch(where ? where[1] : '/workbench/happened', { method: 'POST', headers: FORM, body });
  readRuns();
});

document.querySelector('[data-run]')?.addEventListener('click', async () => {
  const names = onBench().map(cardName);
  if (!names.length) return;
  try {
    const answer = await fetch('/workbench/run', {
      method: 'POST',
      headers: FORM,
      body: new URLSearchParams({ cards: names.join(',') }),
    });
    const said = await answer.json();
    if (!said.started) {
      // The same sentence the panel shows, because it is the same function behind both.
      const panel = document.getElementById('process-panel');
      if (panel) panel.hidden = false;
      readProcess();
      say(said.why || 'This cannot be run yet.');
      return;
    }
    readRuns();
  } catch {
    say('Could not start it.');
  }
});

readRuns();
setInterval(readRuns, 20000);


/* --- a step of your own, and drawings kept to be used again ------------------------------------- */
// "Описываем процесс как в лего." Everything else on this bench stands for something that already
// exists; a step card is the one you draw before the thing exists, which is what describing a
// process requires.
async function addStep(role = 'action') {
  const label = (prompt('What is this step?', '') || '').trim();
  if (!label) return;
  try {
    const answer = await fetch('/cards/step', {
      method: 'POST',
      headers: FORM,
      body: new URLSearchParams({ label, role }),
    });
    const said = await answer.json();
    await pin(
      { kind: 'step', id: said.id, label: said.label },
      { quiet: true, came: 'drawn as a step' }
    );
    await readRoles();
  } catch {
    say('Could not add a step.');
  }
}

// "В финале я должен получить блок, в котором будет кнопка «добавить как идею»."
//
// The end of the flow this whole set describes: a proposal is dragged on, asked about until it is
// understood, and what comes out is an idea with somebody behind it. The route that makes it has
// been here since the set was started and nothing on the page called it, so an idea could be made
// out of a bench only by somebody who knew the URL.
//
// It asks for the line, and does not offer to write one. The summary is what the card shows in a
// pool of two hundred, and after a conversation somebody has just driven, the one sentence they
// would use for it is a thing they have and the console does not.
async function keepThisAsAnIdea() {
  const summary = (prompt('What did this come to? One line.', '') || '').trim();
  if (!summary) return;
  // Everything on the bench, not just what is charged for the next message: the answers, the cards
  // they were about and what was dropped in are all how this was arrived at, and leaving out the
  // ones somebody had switched off would drop half the reasoning without saying so.
  const cards = onBench('.pin[data-kind]:not(.own)').map(cardName).join(',');
  try {
    const answer = await fetch('/ideas/from-bench', {
      method: 'POST',
      headers: FORM,
      body: new URLSearchParams({ cards, summary }),
    });
    const said = await answer.json();
    say(
      said.made
        ? `Written down as yours, out of ${said.cards} card${said.cards === 1 ? '' : 's'}.`
        : said.why || 'Could not write it down.'
    );
  } catch {
    say('Could not write it down.');
  }
}

document.getElementById('as-an-idea')?.addEventListener('click', keepThisAsAnIdea);

// The card an enquiry starts from. "Создаётся карточка начала, например — описание проекта."
//
// A question relates to something, and the first one relates to nothing that has been said yet.
// Without a card to start from, the only thing a first question can hang off is the question
// before it — which is a feed, and a feed is what this is trying to stop being.
//
// Two ways in, because there are two ways somebody arrives at what this is about: a card that is
// already here — a project dragged in is exactly the "описание проекта" of the example — or a
// description they have in their head and no card for yet. Choosing one card first says the
// first; choosing none says the second, and it is typed.
async function beginWith() {
  const chosen = chosenCards();
  let name = chosen.length === 1 ? cardName(chosen[0]) : '';
  if (!name) {
    const what = (prompt('What is this about?', '') || '').trim();
    if (!what) return;
    try {
      const answer = await fetch('/cards/step', {
        method: 'POST',
        headers: FORM,
        // An Object — "something that exists". Not a role invented for this: what an enquiry is
        // about is a thing, and the five are closed (adr/0011).
        body: new URLSearchParams({ label: what.slice(0, 60), role: 'object' }),
      });
      const said = await answer.json();
      name = said.name;
      // The whole of it in the field the role asks for, so the card says what it is rather than
      // only what it is called. The label is a name and names are short; this is the description.
      await fetch('/cards/field', {
        method: 'POST',
        headers: FORM,
        body: new URLSearchParams({ name, role: 'object', field: 'what', value: what }),
      });
      await pin({ kind: 'step', id: said.id, label: said.label }, { came: 'what this is about' });
      await readRoles();
    } catch {
      return say('Could not make a card for it.');
    }
  }
  await beginFrom(name);
}

// Written down, then marked. In that order: a beginning that is only on the page is one somebody
// loses by reloading, and this is the card a long branch hangs from.
async function beginFrom(name) {
  try {
    await fetch('/workbench/start', {
      method: 'POST',
      headers: FORM,
      body: new URLSearchParams({ name, thread: activeThread() }),
    });
  } catch {
    return say('Could not write down what this is about.');
  }
  markBeginning(name);
}

// One card wears the mark, so pointing at another takes it off the first without a second call.
function markBeginning(name) {
  for (const card of surface?.querySelectorAll('.pin') || []) {
    card.classList.toggle('beginning', cardName(card) === name);
  }
  drawTies();
}

// "Процесс, который собрали один раз, должен запускаться второй раз с другими входами."
async function keepTemplate() {
  const names = onBench().map(cardName);
  if (!names.length) return say('There is nothing to save.');
  const name = (prompt('Save this process as:', '') || '').trim();
  if (!name) return;
  const answer = await fetch('/workbench/template', {
    method: 'POST',
    headers: FORM,
    body: new URLSearchParams({ name, cards: names.join(','), thread: activeThread() }),
  });
  const said = await answer.json();
  say(said.kept ? `Saved “${name}” — ${said.steps} steps.` : said.why || 'Could not save it.');
  showTemplates();
}

// Fresh cards every time, which is the point: a template that put the same cards back would be a
// bookmark, and the second run would overwrite what the first produced.
async function useTemplate(name) {
  const answer = await fetch('/workbench/template/use', {
    method: 'POST',
    headers: FORM,
    body: new URLSearchParams({ name }),
  });
  const said = await answer.json();
  if (!said.made) return say(said.why || 'Could not use it.');
  // "Нужно сказать: «в этом шаблоне два поля, которых больше нет»." The cards arrive looking
  // filled in, and the fields a role has since lost are silently not written — right, and
  // invisible, which is the half that was missing.
  if (said.lost?.length) {
    say(
      `This template has ${said.lost.length} field${said.lost.length === 1 ? '' : 's'} its roles ` +
        `no longer ask for, so ${said.lost.length === 1 ? 'it was' : 'they were'} left out: ` +
        said.lost.join(', ')
    );
  }
  // "Позиции — часть того, что человек собрал, и терять их не нужно." A template that remembers
  // where its cards sat is put down in that shape; one saved before it did is laid out the way it
  // always was. The offsets are the drawing's own geometry, so the corner it goes in is decided
  // here — below whatever is already on the bench, rather than on top of it.
  const remembers = said.cards.every((one) => Number.isInteger(one.dx));
  const corner = remembers ? belowEverything() : null;
  for (const one of said.cards) {
    const [kind, ...rest] = one.name.split(':');
    await pin(
      { kind, id: rest.join(':'), label: '' },
      {
        quiet: true,
        came: `made from the template “${name}”`,
        ...(corner
          ? { at: { x: corner.x + one.dx, y: corner.y + one.dy }, exact: true }
          : {}),
      }
    );
  }
  await readRoles();
  await readLines();
  if (!remembers) tidyUp();
  else {
    // Placed on purpose, so the console's own layout leaves them where the drawing put them
    // (042-placed-by-hand.sql) — otherwise the first card to grow sweeps the shape away.
    for (const one of said.cards) {
      const node = surface?.querySelector(`.pin[data-name="${CSS.escape(one.name)}"]`);
      if (node) node.dataset.moved = 'yes';
    }
    moveWasDeliberate();
    drawTies();
    drawMap();
  }
}

// The shelf: everything two cards have made on this bench, newest first. Pressing a row brings
// the card back into view, or puts it back on the surface if it was taken off — which is the whole
// point of the list. Without it the "бесконечная" game ends the first time something scrolls past
// the edge and nobody can find it again.
async function showShelf() {
  const into = document.getElementById('bench-shelf');
  if (!into) return;
  into.replaceChildren();
  let made = [];
  try {
    const answer = await fetch(`/workbench/shelf?thread=${encodeURIComponent(activeThread())}`);
    made = (await answer.json()).made || [];
  } catch {
    return;
  }
  if (!made.length) {
    const none = document.createElement('li');
    none.className = 'saved-none';
    none.textContent = 'nothing made here yet';
    into.appendChild(none);
    return;
  }
  for (const one of made) {
    const row = document.createElement('li');
    const open = document.createElement('button');
    open.type = 'button';
    open.className = 'saved-open';
    open.textContent = one.label;
    // What it was made of, so a shelf of twenty answers is still a shelf somebody can read.
    open.title = one.from.map((name) => labelOf(name)).join('  +  ');
    open.addEventListener('click', () => {
      hideMenu();
      const card = surface?.querySelector(`.pin[data-name="${CSS.escape(one.card)}"]`);
      if (card) {
        bringIntoView(card);
        card.classList.add('about-this');
        setTimeout(() => card.classList.remove('about-this'), 2500);
        return;
      }
      // Off the bench: it is still in the conversation, so unfolding brings its card back rather
      // than asking the pair again.
      say('That one is not on the workbench — unfolding the conversation brings it back.');
    });
    row.appendChild(open);
    into.appendChild(row);
  }
}

async function showTemplates() {
  const into = document.getElementById('bench-templates');
  if (!into) return;
  into.replaceChildren();
  let saved = [];
  try {
    saved = ((await (await fetch('/workbench/templates')).json()).templates) || [];
  } catch {
    return;
  }
  if (!saved.length) {
    const none = document.createElement('li');
    none.className = 'saved-none';
    none.textContent = 'nothing saved yet';
    into.appendChild(none);
    return;
  }
  for (const one of saved) {
    const row = document.createElement('li');
    const open = document.createElement('button');
    open.type = 'button';
    open.className = 'saved-open';
    open.textContent = `${one.name} · ${one.steps} steps`;
    open.addEventListener('click', () => {
      hideMenu();
      useTemplate(one.name);
    });
    const drop = document.createElement('button');
    drop.type = 'button';
    drop.className = 'saved-drop';
    drop.textContent = '×';
    drop.title = `forget ${one.name}`;
    drop.addEventListener('click', async (event) => {
      event.stopPropagation();
      await fetch('/workbench/template/drop', {
        method: 'POST',
        headers: FORM,
        body: new URLSearchParams({ name: one.name }),
      });
      showTemplates();
    });
    row.append(open, drop);
    into.appendChild(row);
  }
}

/* --- the drawing, said in words ----------------------------------------------------------------- */
// "Менеджер собирает схему; кто-то другой должен её понять, не открывая верстак."
//
// One direction is a fact and the other is a guess, and they are shown differently. The
// description is computed — no model call, one right answer, because a description that came back
// differently on two afternoons would be no use for handing work to somebody. The sketch is a
// proposal, and nothing reaches the bench until somebody presses.
async function tellInWords() {
  const names = onBench().map(cardName);
  const panel = document.getElementById('words-panel');
  if (!panel) return;
  panel.hidden = false;
  const into = panel.querySelector('.words-said');
  into.textContent = 'reading…';
  try {
    const answer = await fetch(`/workbench/words?cards=${encodeURIComponent(names.join(','))}`);
    const said = await answer.json();
    into.textContent = said.words || 'There is no process drawn here yet.';
  } catch {
    into.textContent = 'Could not read it.';
  }
}

let sketched = null;

// The step cards on the bench: the ones a drawing is made of, and the only ones a redraw touches.
// Everything else on a workbench stands for something that exists outside it — a session, an idea,
// a project — and taking one of those off because somebody rewrote a description would be losing
// something the description was never about.
function stepsOnTheBench() {
  return onBench('.pin[data-kind="step"]');
}

async function sketchFromWords() {
  const panel = document.getElementById('words-panel');
  const field = panel?.querySelector('.words-in');
  const shown = panel?.querySelector('.words-offer');
  if (!field || !shown) return;
  shown.textContent = 'thinking…';
  try {
    const answer = await fetch('/workbench/sketch', {
      method: 'POST',
      headers: FORM,
      body: new URLSearchParams({ words: field.value }),
    });
    const said = await answer.json();
    if (!said.read) {
      shown.textContent = said.why || 'Could not read that.';
      sketched = null;
      return;
    }
    sketched = said;
    // Shown as what it is: a proposal, in the words it would put on the cards.
    shown.textContent = said.steps
      .map((one, index) => `${index + 1}. ${one.role} — ${one.label}${one.words ? `: ${one.words}` : ''}`)
      .concat(said.lines.map((one) => `   ${one.from} → ${one.to} (${one.kind}${one.says ? `: ${one.says}` : ''})`))
      .join('\n');
    panel.querySelector('[data-keep-sketch]').hidden = false;
    // Redrawing is offered only when there is something to redraw. On an empty bench the two
    // buttons would do the same thing under different words, which is a choice nobody can make.
    panel.querySelector('[data-redraw-sketch]').hidden = !stepsOnTheBench().length;
  } catch {
    shown.textContent = 'Could not read that.';
  }
}

document.getElementById('words-panel')?.addEventListener('click', async (event) => {
  const button = event.target.closest('button');
  if (!button) return;
  if (button.dataset.sketch !== undefined) return sketchFromWords();
  if (button.dataset.wordsOff !== undefined) {
    document.getElementById('words-panel').hidden = true;
    return;
  }
  const redrawing = button.dataset.redrawSketch !== undefined;
  if ((button.dataset.keepSketch === undefined && !redrawing) || !sketched) return;
  // "Поправить процесс словами нельзя — только собрать рядом второй и удалить первый." Taking the
  // old steps off first is the whole difference, and it is one press of undo away — the cards are
  // step cards, which stand for nothing outside this drawing, so nothing else loses anything.
  if (redrawing) {
    const going = stepsOnTheBench();
    for (const pin of going) {
      placed.delete(cardName(pin));
      pin.remove();
    }
    if (going.length) say(`Took ${going.length} step${going.length === 1 ? '' : 's'} off.`);
  }
  const answer = await fetch('/workbench/sketch/keep', {
    method: 'POST',
    headers: FORM,
    body: new URLSearchParams({
      steps: sketched.steps.map((one) => `${one.role}|${one.label}|${one.words}`).join('\n'),
      lines: sketched.lines.map((one) => `${one.from}|${one.to}|${one.kind}|${one.says}`).join('\n'),
    }),
  });
  const said = await answer.json();
  for (const one of said.cards || []) {
    const [kind, ...rest] = one.name.split(':');
    await pin(
      { kind, id: rest.join(':'), label: '' },
      { quiet: true, came: 'drawn from a description' }
    );
  }
  await readRoles();
  await readLines();
  tidyUp();
  button.hidden = true;
  sketched = null;
});

document.querySelector('[data-words]')?.addEventListener('click', tellInWords);

/* --- how big it is ---------------------------------------------------------------------------- */
const ZOOMS = [0.5, 0.65, 0.8, 1, 1.25, 1.5];
const FULL_SIZE = ZOOMS.indexOf(1);

function zoomTo(index, around) {
  const next = ZOOMS[Math.min(ZOOMS.length - 1, Math.max(0, index))];
  const frame = canvas.getBoundingClientRect();
  const at = around || { x: frame.width / 2, y: frame.height / 2 };
  // Keep the point under the cursor where it is, which is what makes zooming feel like zooming
  // rather than like the page jumping.
  view.x = at.x - ((at.x - view.x) * next) / view.scale;
  view.y = at.y - ((at.y - view.y) * next) / view.scale;
  view.scale = next;
  applyView();
  try {
    // The *scale*, not its index. An index is a reference into an array that is allowed to
    // change, and when this one gained two entries every browser holding a "2" silently started
    // meaning 80% where it had meant 100%. A number that means a size still means that size.
    localStorage.setItem('agent-desk:bench-size', String(next));
  } catch {
    // Not remembering the size is not a reason to refuse to change it.
  }
}

document.addEventListener('click', (event) => {
  const button = event.target.closest('[data-zoom]');
  if (!button) return;
  const step = Number(button.dataset.zoom);
  if (step === 0) {
    view = { x: 0, y: 0, scale: 1 };
    applyView();
    return;
  }
  zoomTo(ZOOMS.indexOf(view.scale) + step);
});

// "Без нажатия ctrl колёсико мыши не задействовано — давай скейлинг на него повесим, когда курсор
// на верстаке." It was not doing anything else: the canvas is `overflow: hidden`, so a plain wheel
// over the bench scrolled nothing and zoomed nothing. Ctrl still works, because that is the
// browser-wide gesture and somebody's hands already know it.
//
// Except over something that scrolls. A long answer and a card opened to `full` have their own
// scrollbars, and a wheel that zoomed the bench instead of moving the text somebody is reading
// would be the gesture taking priority over the thing it is pointed at. Ctrl overrides that in
// turn: held down, it means zoom wherever the pointer is.
function scrollsItself(target) {
  for (let at = target; at && at !== canvas; at = at.parentElement) {
    if (at.scrollHeight > at.clientHeight + 1 && getComputedStyle(at).overflowY !== 'visible') {
      return true;
    }
  }
  return false;
}

canvas?.addEventListener(
  'wheel',
  (event) => {
    if (!event.ctrlKey && scrollsItself(event.target)) return;
    event.preventDefault();
    const frame = canvas.getBoundingClientRect();
    zoomTo(ZOOMS.indexOf(view.scale) + (event.deltaY < 0 ? 1 : -1), {
      x: event.clientX - frame.left,
      y: event.clientY - frame.top,
    });
  },
  { passive: false }
);

/* --- the lines ---------------------------------------------------------------------------------*/
// Drawn from the cards' stored positions rather than measured off the screen, so they are correct
// at any zoom and while something is being dragged.
async function loadTies() {
  if (!ties) return;
  const cards = [...surface.querySelectorAll('.pin[data-kind]:not(.own)')].map(cardName).join(',');
  if (!cards) {
    tieList = [];
    drawTies();
    return;
  }
  try {
    const response = await fetch(`/workbench/ties?cards=${encodeURIComponent(cards)}`);
    tieList = response.ok ? await response.json() : [];
  } catch {
    tieList = [];
  }
  drawTies();
}

// The server knows how ideas relate to each other; the page knows what a question went out with.
// Both are lines on the same surface.
function everyTie() {
  return [...tieList, ...ownTies, ...processTies()];
}

function showing(name) {
  const pin = surface?.querySelector(`.pin[data-name="${CSS.escape(name)}"]`);
  return pin && !pin.classList.contains('put-away') ? pin : null;
}

// Three things made this the second most expensive thing on the surface, and all three are the
// same mistake in different clothes: work repeated once per line, on a surface where the number of
// lines grows with the number of cards.
//
//   * every line looked both its ends up with `querySelector` over the whole surface;
//   * every line read `offsetWidth` and `offsetHeight` off its cards *after* the last line had
//     already been appended, so the browser had to lay the page out again to answer;
//   * and `markHintCounts` then walked every line again, for every card, to count them.
//
// So the cards are gathered once, measured once before anything is written, and the lines are
// built into a fragment that goes in in one go. 17ms on 35 cards, and the same shape of curve as
// `markOffEdge` above.
function drawTies() {
  // What a button reaches is decided by the lines, so it is said again whenever they are drawn.
  // Said once when the card arrived, it went on claiming "joined to nothing" after somebody joined
  // it to something — a control describing a scope it no longer has (059).
  for (const one of surface?.querySelectorAll('.pin[data-kind="button"]') || []) {
    saysWhatItReaches(one);
  }
  if (!ties) return;

  // Read. One pass over the cards, and every measurement taken before a single write.
  const pins = new Map();
  for (const pin of surface?.querySelectorAll('.pin[data-name]') || []) {
    if (pin.classList.contains('put-away')) continue;
    pins.set(pin.dataset.name, {
      pin,
      w: pin.offsetWidth || CARD_WIDTH,
      h: pin.offsetHeight || 120,
    });
  }
  const joined = new Map();
  const made = document.createDocumentFragment();
  let drew = 0;
  for (const tie of everyTie()) {
    joined.set(tie.from, (joined.get(tie.from) || 0) + 1);
    joined.set(tie.to, (joined.get(tie.to) || 0) + 1);
    // Both ends have to be *visible*, not merely present: a card put away with the conversation
    // is still in the document, and drawing to it filled a corner of the surface with lines
    // going to nothing.
    const one = pins.get(tie.from);
    const other = pins.get(tie.to);
    const a = placed.get(tie.from);
    const b = placed.get(tie.to);
    if (!one || !other || !a || !b) continue;

    // "Связи выглядят как прямые с углом линии, чтобы визуально это напоминало некий каталог из
    // карточек." An elbow rather than a curve: a catalogue is read as a tree, and a tree is drawn
    // with right angles. Out of the right of one, along, down, and into the left of the other.
    const rightward = a.x <= b.x;
    const from = { x: a.x + (rightward ? one.w : 0), y: a.y + one.h / 2 };
    const to = { x: b.x + (rightward ? 0 : other.w), y: b.y + other.h / 2 };
    // The corner sits in the gap between the two, so the vertical run is in clear space rather
    // than across a card.
    const bend = from.x + (to.x - from.x) / 2;

    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute(
      'd',
      `M ${from.x} ${from.y} H ${bend} V ${to.y} H ${to.x}`
    );
    path.setAttribute('class', `tie ${tie.says.replace(/\s+/g, '-')}`);
    path.setAttribute('fill', 'none');
    path.setAttribute('marker-end', 'url(#tie-end)');
    made.appendChild(path);

    const label = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    label.setAttribute('x', String(bend + 5));
    label.setAttribute('y', String((from.y + to.y) / 2 - 4));
    label.setAttribute('text-anchor', 'middle');
    label.setAttribute('class', `tie-label${tie.kind ? ` is-${tie.kind}` : ''}`);
    label.textContent = tie.says;
    if (tie.drawn) {
      // Only a line somebody drew can be changed. The ones this console works out for itself —
      // which project a session is in, what a question went out with — are readings of facts, and
      // a menu offering to edit one would be offering to edit the fact.
      label.classList.add('can-press');
      label.addEventListener('click', (event) => {
        event.stopPropagation();
        showLineMenu(tie, event.clientX, event.clientY);
      });
    }
    made.appendChild(label);
    drew += 1;
  }

  // Write. Once for the lines, and once per card for the little count beside its name — which is
  // now a lookup in a map built above rather than a walk over every line for every card.
  ties.replaceChildren(made);
  ties.hidden = drew === 0;
  for (const [name, one] of pins) markHintCounts(one.pin, joined.get(name) || 0);
}

// Whether a card is on the screen right now. Arithmetic, not `getBoundingClientRect` — the surface
// carries one transform, so a card's place on screen is `view.x + at.x * scale`, and asking the
// browser instead is what cost `markOffEdge` 19ms a frame before it was written this way.
function onTheScreen(pin) {
  const at = placed.get(cardName(pin));
  const frame = canvas?.getBoundingClientRect();
  if (!at || !frame) return true;
  const left = view.x + at.x * view.scale;
  const top = view.y + at.y * view.scale;
  const right = left + (pin.offsetWidth || CARD_WIDTH) * view.scale;
  const bottom = top + (pin.offsetHeight || 120) * view.scale;
  return right > 0 && left < frame.width && bottom > 0 && top < frame.height;
}

// Put a card in the middle of the window. One copy of the arithmetic, used by the dots that reach
// a card off the edge and by the console when it says what a question was taken to be about.
// "Тот набор карточек, что взят сейчас в работу при отправке последнего запроса, должен
// перемещаться в центр экрана."
//
// The snapshot of what went out is placed clear of everything already on the bench, which means
// below it — and on a bench of forty cards that is off the bottom of the window. Somebody pressed
// send and the record of what they sent appeared somewhere they could not see, which is the same
// as it not appearing.
//
// The view moves, not the cards. A layout somebody arranged by hand is not the console's to
// rearrange because a question was asked (042), and moving the cards would also move them out from
// under the lines drawn to them.
//
// It zooms out to fit and never in. Sending a question is not a reason to magnify a bench, and a
// zoom that changed in both directions on every send would be a surface nobody could hold still.
function bringTheseIntoView(names) {
  const spots = names
    .map((name) => ({ at: placed.get(name), el: surface?.querySelector(`.pin[data-name="${CSS.escape(name)}"]`) }))
    .filter((one) => one.at && one.el);
  const frame = canvas?.getBoundingClientRect();
  if (!spots.length || !frame) return;
  const left = Math.min(...spots.map((one) => one.at.x));
  const top = Math.min(...spots.map((one) => one.at.y));
  const right = Math.max(...spots.map((one) => one.at.x + (one.el.offsetWidth || CARD_WIDTH)));
  const bottom = Math.max(...spots.map((one) => one.at.y + one.el.offsetHeight));
  const pad = 40;
  const fits = Math.min(
    (frame.width - pad) / Math.max(1, right - left),
    (frame.height - pad) / Math.max(1, bottom - top)
  );
  if (fits < view.scale) {
    view.scale = ZOOMS.reduce((best, one) => (one <= fits && one > best ? one : best), ZOOMS[0]);
  }
  view.x = frame.width / 2 - ((left + right) / 2) * view.scale;
  view.y = frame.height / 2 - ((top + bottom) / 2) * view.scale;
  applyView();
}

function bringIntoView(pin) {
  const at = placed.get(cardName(pin));
  const frame = canvas?.getBoundingClientRect();
  if (!at || !frame) return;
  view.x = frame.width / 2 - (at.x + CARD_WIDTH / 2) * view.scale;
  view.y = frame.height / 2 - (at.y + 40) * view.scale;
  applyView();
}

/* --- how much could be going on at once -------------------------------------------------------- */
// "Число должно вычисляться и объясняться, а не задаваться." A count on its own is a number to
// argue with; a count that says which project is free and why the others are not is one somebody
// can act on — so the line and the reasons arrive together and are shown together.
//
// Read on the same beat as the board, because every input to it — a seat taken, a budget spent, a
// project disarmed — is something the board push is already about.
async function readRoom() {
  const holder = document.getElementById('room');
  if (!holder) return;
  try {
    const said = await (await fetch('/room')).json();
    holder.querySelector('.room-said').textContent = said.said || '';
    const list = holder.querySelector('.room-lines');
    list.replaceChildren();
    for (const line of said.lines || []) {
      const row = document.createElement('li');
      row.textContent = line;
      list.appendChild(row);
    }
    holder.hidden = !(said.lines || []).length;
  } catch {
    // The board is still the board. A count that could not be read is left as it was rather than
    // replaced with a zero, which would read as "nothing can run".
  }
}

/* --- what is off the screen ------------------------------------------------------------------- */
// More useful on a surface than it was on a list: a card you moved somewhere and then panned away
// from is a card that still goes into the next message.
// Which cards are off the screen, worked out rather than measured.
//
// This asked the browser for `getBoundingClientRect()` on every card, in a loop that was also
// appending to the document — so each read forced a fresh layout of the whole page, once per card.
// Measured on 35 cards: 19ms, inside `applyView`, which runs on every frame of a pan. On the two
// hundred cards this idea is about it is over a hundred, which is a workbench that does not move.
//
// A card's place on the screen is arithmetic: the surface carries one transform, so screen-x is
// `view.x + at.x * scale`. The only thing that has to be asked is how big a card is, and that is
// asked for all of them before anything is written — one layout for the whole pass instead of one
// per card.
function markOffEdge() {
  const edge = document.getElementById('off-edge');
  if (!edge || !canvas) return;
  const frame = canvas.getBoundingClientRect();

  // Read. Nothing below this line touches the document until every measurement is taken.
  const away = [];
  for (const pin of surface.querySelectorAll('.pin')) {
    const at = placed.get(cardName(pin));
    if (!at) continue;
    const left = view.x + at.x * view.scale;
    const top = view.y + at.y * view.scale;
    const right = left + (pin.offsetWidth || CARD_WIDTH) * view.scale;
    const bottom = top + (pin.offsetHeight || 120) * view.scale;
    if (right > 0 && left < frame.width && bottom > 0 && top < frame.height) continue;
    away.push({ pin, at, said: pin.querySelector('.pin-label')?.textContent || 'a card over there' });
  }

  // Write. Once, into a fragment, so the dots do not each cost a pass of their own.
  const made = document.createDocumentFragment();
  for (const one of away) {
    const dot = document.createElement('button');
    dot.type = 'button';
    dot.className = 'edge-dot';
    dot.title = one.said;
    dot.setAttribute('aria-label', `bring ${one.said} into view`);
    dot.addEventListener('click', () => bringIntoView(one.pin));
    made.appendChild(dot);
  }
  edge.replaceChildren(made);
  edge.hidden = away.length === 0;
}

// One button, because a surface you can move things about on is a surface you can lose things on.
document.querySelector('[data-tidy]')?.addEventListener('click', tidyUp);
document.querySelector('[data-undo]')?.addEventListener('click', undoBench);

window.addEventListener('resize', () => {
  markOffEdge();
  drawTies();
});

recallLayout();
try {
  // `getItem` returns null when nothing is stored and `Number(null)` is 0 — which was once a
  // valid index and therefore a silent wrong default, so the absent case is checked as a string
  // first. Anything that is not one of the sizes on offer falls back to full size rather than to
  // whatever it rounds to.
  const stored = localStorage.getItem('agent-desk:bench-size');
  const remembered = stored === null ? 1 : Number(stored);
  view.scale = ZOOMS.includes(remembered) ? remembered : 1;
} catch {
  view.scale = 1;
}
applyView();

/* --- what the right mouse button offers -------------------------------------------------------- */
// "ПКМ в поле верстака открывает варианты действий, первые из которых — добавить карточку-ссылку
// или файл и прочее."
//
// On the *background* only. Taking the browser's own menu away from a text field would take paste
// with it, and this is a window people paste into all day — so a right-click on a card, a field
// or a button is left entirely alone.
const benchMenu = document.getElementById('bench-menu');

function showMenu(x, y) {
  if (!benchMenu) return;
  // Rebuilt every time it opens: a list kept in step by hand is a list that offers a workbench
  // somebody deleted.
  showBenches();
  showTemplates();
  showShelf();
  benchMenu.hidden = false;
  const frame = document.getElementById('bench-canvas').getBoundingClientRect();
  // Kept inside the window: a menu opened near the bottom edge that runs off it is a menu with
  // half its items unreachable.
  const width = benchMenu.offsetWidth;
  const height = benchMenu.offsetHeight;
  benchMenu.style.left = `${Math.min(x, frame.right - width - 8)}px`;
  benchMenu.style.top = `${Math.min(y, window.innerHeight - height - 8)}px`;
}

function hideMenu() {
  if (benchMenu) benchMenu.hidden = true;
}

const BACKGROUND_MENU = [
  { what: 'Add a link…', add: 'link' },
  { what: 'Add a file…', add: 'file' },
  { what: 'Add a folder…', add: 'folder' },
  { what: 'Add a note', add: 'note' },
  { what: 'Lay it out again', add: 'tidy', apart: true },
  { what: 'Fit everything on screen', add: 'fit' },
  { what: 'Take everything off', add: 'clear' },
];

function showBackgroundMenu(x, y) {
  if (!benchMenu) return;
  benchMenu.replaceChildren();
  for (const item of BACKGROUND_MENU) {
    const row = document.createElement('li');
    if (item.apart) row.className = 'sep';
    const button = document.createElement('button');
    button.type = 'button';
    button.dataset.add = item.add;
    button.textContent = item.what;
    row.appendChild(button);
    benchMenu.appendChild(row);
  }
  showMenu(x, y);
}

document.getElementById('bench-canvas')?.addEventListener('contextmenu', (event) => {
  // A card gets its own menu; a field or a button keeps the browser's, because taking paste away
  // from somebody reaching for it is worse than any menu is good.
  if (event.target.closest('button, a, input, textarea, select')) return;
  const pin = event.target.closest('.pin');
  event.preventDefault();
  if (pin) showCardMenu(pin, event.clientX, event.clientY);
  else showBackgroundMenu(event.clientX, event.clientY);
});

document.addEventListener('click', (event) => {
  if (!event.target.closest('#bench-menu')) hideMenu();
});
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') hideMenu();
});

benchMenu?.addEventListener('click', (event) => {
  const button = event.target.closest('[data-add]');
  if (!button) return;
  hideMenu();
  const what = button.dataset.add;
  if (what === 'note') addOwnBlock();
  else if (what === 'link') addOwnBlock('link');
  else if (what === 'file') addOwnBlock('file');
  else if (what === 'tidy') tidyUp();
  else if (what === 'fit') fitEverything();
  else if (what === 'folder') addFolder();
  else if (what === 'clear') clearBench();
  else if (what === 'keep') keepBench();
  else if (what === 'step') addStep();
  else if (what === 'about') beginWith();
  else if (what === 'button') addButton();
  else if (what === 'check') addCheck();
  else if (what === 'combining') howCombiningWorks();
  else if (what === 'template') keepTemplate();
});

// The conversation folded away, and back. What folds is every card holding a block — the cards
// somebody dropped stay, because those are what the next question is about, and folding them
// would be answering a different question.
function foldConversation() {
  const cards = [...(surface?.querySelectorAll('.pin.block-card') || [])];
  if (!cards.length) return;
  const folding = !cards[0].classList.contains('put-away');
  // What the conversation brought goes with it.
  //
  // Folding only the block cards left every idea those blocks had written still on the surface:
  // on a real console that is thirty-odd cards nobody dropped there, and a process you are trying
  // to draw is invisible among them. A card *somebody put here* stays — that is the whole
  // distinction, and it is recorded when the card arrives (`bringItsKin`) rather than guessed at
  // now.
  for (const card of [...cards, ...surface.querySelectorAll('.pin[data-brought="yes"]')]) {
    card.classList.toggle('put-away', folding);
    if (folding) {
      card.dataset.viewBefore = card.dataset.view || 'hint';
      setView(card, 'hint');
    } else if (card.dataset.viewBefore) {
      setView(card, card.dataset.viewBefore);
    }
  }
  settleOverlaps();
}

/* --- the menu on a card ------------------------------------------------------------------------ */
// "ПКМ на карточке на верстаке открывает меню управления, которое помимо прочего может установить
// связи с элементами."
//
// Joining two cards is the thing that needed a gesture and did not have one: the lines the console
// draws are the ones it knows about, and there was no way to say "these two belong together"
// about anything else. Pick one card, then the other.
let joiningFrom = null;

// The lines somebody drew to or from this card, **and can see**.
//
// Two filters and both are load-bearing. Only lines somebody drew, because the ones this console
// works out for itself — which project a session is in, what a question went out with — are
// readings of facts, and rubbing one out would be rubbing out the fact.
//
// And only lines with both ends on this bench. A line is a statement about two cards rather than
// about a surface, so `card_tie` is not scoped to a chat — measured in a browser, a card with two
// lines drawn on this bench offered to rub out three, the third being a line to a card on another
// chat's workbench. Offering to remove something nobody can see is the same mistake the undo had,
// and it is worse here because it is presented as a count somebody is reading.
function linesOf(name) {
  return drawnTies.filter(
    (line) =>
      (line.from === name || line.to === name) && showing(line.from) && showing(line.to)
  );
}

async function rubOutLinesOf(name) {
  const going = linesOf(name);
  for (const line of going) await rubOutLine(line.id);
  say(`Rubbed out ${going.length} line${going.length === 1 ? '' : 's'}.`);
}

// A collection, laid back out into the cards it holds.
//
// A card that is already on the bench is left where it is rather than added a second time, and the
// count says how many actually came back — "разложить обратно" over a bench that still has three
// of the five is two cards, and a message claiming five would be describing a different bench.
async function layBackOut(card) {
  const rows = [...card.querySelectorAll('.collected li[data-kind]')];
  let back = 0;
  for (const row of rows) {
    const name = `${row.dataset.kind}:${row.dataset.id}`;
    if (surface.querySelector(`.pin[data-name="${CSS.escape(name)}"]`)) continue;
    await pin(
      { kind: row.dataset.kind, id: row.dataset.id, label: row.dataset.label },
      { quiet: true, came: 'laid back out of a group' }
    );
    back += 1;
  }
  placed.delete(cardName(card));
  card.remove();
  syncTargets();
  drawTies();
  const already = rows.length - back;
  say(
    `Laid out ${back} card${back === 1 ? '' : 's'}` +
      (already ? `; ${already} ${already === 1 ? 'was' : 'were'} already on the workbench.` : '.')
  );
}

function cardMenuFor(pin) {
  const name = pin.dataset.name;
  if (pin.classList.contains('collection')) {
    return [
      { what: 'lay it back out', act: () => layBackOut(pin) },
      { what: 'a line', act: () => setView(pin, 'hint') },
      { what: 'everything', act: () => setView(pin, 'full') },
      {
        what: 'take it off the workbench',
        act: () => {
          placed.delete(cardName(pin));
          pin.remove();
          syncTargets();
          drawTies();
        },
      },
    ];
  }
  const joining = joiningFrom && joiningFrom !== name;
  return [
    joining
      ? { what: `join to “${labelOf(joiningFrom)}”`, act: () => finishJoin(name) }
      : { what: 'join this to another card…', act: () => startJoin(name) },
    // "Линии стираются по одной. Когда карточка ошиблась ролью и обросла пятью неправильными
    // связями, это пять нажатий и меню каждый раз." Offered only when there is more than one, so
    // the menu does not carry a second way to do what the line's own menu already does.
    ...(linesOf(name).length > 1
      ? [{ what: `rub out all ${linesOf(name).length} of its lines`, act: () => rubOutLinesOf(name) }]
      : []),
    { what: 'why is this here?', act: () => whyItIsHere(pin) },
    { what: 'a line', act: () => setView(pin, 'hint') },
    { what: 'what it is', act: () => setView(pin, 'metadata') },
    { what: 'everything', act: () => setView(pin, 'full') },
    // Only the two kinds that hold behaviour. Keeping an idea card "as a tool" would be keeping a
    // thing that is already kept, under a second name, in a second list (065).
    ...(pin.dataset.kind === 'button' || pin.dataset.kind === 'check'
      ? [{ what: 'keep it as a tool', act: () => keepAsATool(pin) }]
      : []),
    {
      what: pin.classList.contains('spent') ? 'put it back in the message' : 'leave it out of the message',
      act: () => {
        pin.classList.toggle('spent');
        syncTargets();
      },
    },
    { what: 'take it off the workbench', act: () => { pin.remove(); syncTargets(); drawTies(); } },
  ];
}

// "Тыкнуть в карточку и получить не текст, а цепочку: вот эта задача упала с такой ошибкой,
// поэтому эта идея не закрыта, поэтому этот блокер здесь."
//
// Every step carries the column it was read out of, and the page shows that: a chain whose steps
// are only sentences is a paragraph with line breaks, and somebody who does not believe one still
// has to take the console's word for it.
async function whyItIsHere(holder) {
  const name = cardName(holder);
  let steps = [];
  try {
    const answer = await fetch(
      `/workbench/why?name=${encodeURIComponent(name)}&thread=${encodeURIComponent(activeThread())}`
    );
    steps = (await answer.json()).steps || [];
  } catch {
    say('It could not be read.');
    return;
  }
  const into = holder.querySelector('.pin-body');
  if (!into) return;
  let box = into.querySelector('.why-here');
  if (!box) {
    box = document.createElement('div');
    box.className = 'why-here';
    into.prepend(box);
  }
  box.replaceChildren();
  if (!steps.length) {
    // "Nothing says" is an answer. An invented reason is the one this whole thing is against.
    const none = document.createElement('p');
    none.className = 'small dim';
    none.textContent = 'Nothing here says why this is on the workbench.';
    box.appendChild(none);
  }
  const list = document.createElement('ol');
  for (const step of steps) {
    const row = document.createElement('li');
    row.textContent = step.said;
    const source = document.createElement('span');
    source.className = 'why-from';
    source.textContent = step.from;
    row.appendChild(source);
    list.appendChild(row);
  }
  if (steps.length) box.appendChild(list);
  // Opened, because a chain written into a folded card is a chain nobody sees.
  if (holder.dataset.view === 'hint') setView(holder, 'metadata');
}

function labelOf(name) {
  return (
    surface?.querySelector(`.pin[data-name="${CSS.escape(name)}"] .pin-label`)?.textContent || name
  );
}

function startJoin(name) {
  joiningFrom = name;
  surface?.querySelector(`.pin[data-name="${CSS.escape(name)}"]`)?.classList.add('joining');
}

async function finishJoin(name) {
  if (!joiningFrom || joiningFrom === name) return;
  const from = joiningFrom;
  surface?.querySelector('.pin.joining')?.classList.remove('joining');
  joiningFrom = null;
  // Typed from the roles at both ends, and kept. It used to be a line held in the tab saying
  // "goes with", which vanished when the tab did and said nothing either way — draw a line out of
  // a Decision and it is a branch before anybody has chosen anything.
  const kind = naturalTie(
    surface?.querySelector(`.pin[data-name="${CSS.escape(from)}"]`),
    surface?.querySelector(`.pin[data-name="${CSS.escape(name)}"]`)
  );
  const words = tieKinds[kind]?.wants_words
    ? (prompt('When does it go this way?', '') || '').trim()
    : '';
  await drawLine(from, name, kind, words);
}

function showCardMenu(pin, x, y) {
  if (!benchMenu) return;
  benchMenu.replaceChildren();
  for (const item of cardMenuFor(pin)) {
    const row = document.createElement('li');
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = item.what;
    button.addEventListener('click', () => {
      hideMenu();
      item.act();
    });
    row.appendChild(button);
    benchMenu.appendChild(row);
  }
  showMenu(x, y);
}

// A folder from this machine, as a card. It is a path somebody types, and it stays a path: what
// travels with a message is what is in the folder, not what the files say.
function addFolder() {
  const said = window.prompt('Which folder? A full path, starting at /');
  if (!said) return;
  pin(
    { kind: 'folder', id: said.trim(), label: said.trim().split('/').filter(Boolean).pop() || said },
    { came: 'typed in as a folder' }
  );
}

function clearBench() {
  // Everything comes off, including the rings. What was asked is still in the store and comes
  // back with the thread — this clears the surface, not the conversation.
  for (const node of surface?.querySelectorAll('.pin, .ring') || []) node.remove();
  placed = new Map();
  ownTies.length = 0;
  // The lines went with them, so the record of having drawn them has to go too — otherwise a
  // conversation put back on a cleared bench comes back with no lines between its cards.
  joined.clear();
  wentWith.clear();
  letGoOfAttached();
  rememberLayout();
  syncTargets();
  drawTies();
  emptyOrNot();
}

// "Сценарий 11 раскладывает карточки по смыслу, человек двигает их сам, а «tidy up» сметает и то и
// другое в сетку."
//
// It did, and that is the reason a bench somebody had arranged was never arranged for long: the
// one control that promises to sort out a mess could not tell the mess from the work. It emptied
// the whole layout and laid every card out in a grid, so a set of cards put on the left because
// they belonged on the left went into column two.
//
// So it lays out what nobody placed, *around* what somebody did — collision avoidance is already
// doing that work, and the cards it must not overlap are exactly the ones being left alone. And it
// says what it left, because a button that did less than everything and did not mention it is a
// button somebody presses twice.
// Which column each kind of card belongs in, from the server — the same order the workbench
// diagram lays a card out in, because a copy here would be a second place to be wrong.
let column = { of: {}, beside: 0 };
try {
  column = JSON.parse(document.getElementById('bench-columns')?.textContent || 'null') || column;
} catch {
  // Everything in one column is a worse layout, not a broken one.
}

function columnOf(kind) {
  return column.of[kind] ?? column.beside;
}

// An enquiry is laid out by following its lines; anything else by what each card is.
//
// "Наши линии-локти рисуются от карточки к карточке и с этим справятся; чего нет — раскладки,
// которая не рвёт длинную ветку на куски, когда та начинает ветвиться вширь." A column per kind is
// right for a pile of sessions and ideas and wrong for an enquiry: every answer in one column and
// every question in another tears a branch in half the moment it is longer than two steps.
//
// Which of the two is decided by whether this chat has said what it is about (050). That is the
// mark of an enquiry and it is a thing somebody set, rather than a guess made from the shape of
// the bench — where "there are some lines" is true of almost every bench.
function tidyUp() {
  if (surface?.querySelector('.pin.beginning')) return layOutTheEnquiry();
  layOutInColumns();
}

async function layOutTheEnquiry() {
  const loose = [...surface.querySelectorAll('.pin:not([data-moved])')];
  const kept = surface.querySelectorAll('.pin[data-moved]').length;
  if (!loose.length) {
    if (kept) say(`Nothing to lay out — you placed all ${kept} of these yourself.`);
    return;
  }
  // Every measurement before anything moves, for the reason `layOutInColumns` gives below: placing
  // one card changes the layout the next measurement would be answered from.
  const cards = loose.map((pin) => ({
    name: cardName(pin),
    width: pin.offsetWidth || CARD_WIDTH,
    height: pin.offsetHeight || 120,
  }));
  let spots = {};
  try {
    const answer = await fetch('/workbench/arrange', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ cards, lines: everyTie() }),
    });
    spots = (await answer.json()).spots || {};
  } catch {
    // The surface somebody already has, which is what a failed layout should leave them with.
    return say('Could not work out a layout for this one.');
  }
  for (const pin of loose) {
    const at = spots[cardName(pin)];
    if (!at) continue;
    placed.delete(cardName(pin));
    place(pin, at, { avoid: false });
  }
  view.x = 0;
  view.y = 0;
  applyView();
  drawTies();
  drawRings();
  moveWasDeliberate();
  say(
    kept
      ? `Followed the lines through ${loose.length}. The ${kept} you placed yourself stayed where they were.`
      : `Followed the lines through ${loose.length} cards.`
  );
}

function layOutInColumns() {
  const loose = [...surface.querySelectorAll('.pin:not([data-moved])')];
  const kept = surface.querySelectorAll('.pin[data-moved]').length;
  // Only the loose ones forget where they were. Emptying the whole map took the placed cards'
  // positions with it, which is the sweep this is fixing.
  for (const pin of loose) placed.delete(cardName(pin));

  // Every height first, because placing one card changes the layout the next measurement would be
  // answered from — the mistake that cost a pan 20ms a frame, one function over.
  const tall = new Map(loose.map((pin) => [pin, pin.offsetHeight || 120]));

  // "Раскладка, которая не превращается в кашу на сотне элементов." It was three columns filled
  // in the order the cards happened to arrive, so a project card, the answer about it and an idea
  // from last week ended up side by side, and a hundred cards were a column twenty screens long
  // with nothing to navigate by.
  //
  // A column per kind, left to right in the order things contain each other: the project, the
  // checkout, the session, what is blocking it, the conversation, the ideas out of it, the steps
  // drawn after those. Then a bench of a hundred is read by walking across it, and where a card is
  // says what it is before you read a word of it.
  //
  // Positions are worked out rather than swept into by collision avoidance: that gives up after
  // forty steps down and starts a column of its own, which on a hundred cards is exactly the
  // porridge this replaces.
  const down = new Map();
  for (const pin of loose) {
    const at = columnOf(pin.dataset.kind);
    const y = down.get(at) ?? 20;
    place(pin, { x: 20 + at * (CARD_WIDTH + GAP * 2), y }, { avoid: false });
    down.set(at, y + tall.get(pin) + GAP);
  }
  view.x = 0;
  view.y = 0;
  applyView();
  drawTies();
  drawRings();
  // "Разложенный по колонкам верстак" is one of the four things the undo was asked for by name.
  moveWasDeliberate();
  if (!loose.length && kept) {
    say(`Nothing to lay out — you placed all ${kept} of these yourself.`);
  } else if (kept) {
    say(`Laid out ${loose.length}. The ${kept} you placed yourself stayed where they were.`);
  }
}

// Everything on screen at once, whatever size that takes. The counterpart to tidying: it moves
// the view rather than the cards, so a layout somebody arranged on purpose survives it.
function fitEverything() {
  const cards = [...(surface?.querySelectorAll('.pin') || [])];
  if (!cards.length) return;
  const spots = cards.map((pin) => ({ at: placed.get(cardName(pin)), el: pin })).filter((one) => one.at);
  if (!spots.length) return;
  const left = Math.min(...spots.map((one) => one.at.x));
  const top = Math.min(...spots.map((one) => one.at.y));
  const right = Math.max(...spots.map((one) => one.at.x + one.el.offsetWidth));
  const bottom = Math.max(...spots.map((one) => one.at.y + one.el.offsetHeight));
  const frame = document.getElementById('bench-canvas').getBoundingClientRect();
  const pad = 40;
  const scale = Math.min(
    1,
    (frame.width - pad) / Math.max(1, right - left),
    (frame.height - pad) / Math.max(1, bottom - top)
  );
  view.scale = ZOOMS.reduce((best, one) => (one <= scale && one > best ? one : best), ZOOMS[0]);
  view.x = frame.width / 2 - ((left + right) / 2) * view.scale;
  view.y = frame.height / 2 - ((top + bottom) / 2) * view.scale;
  applyView();
  drawTies();
  drawRings();
}

/* --- the conversation, as cards on the surface ------------------------------------------------- */
// "Есть только верстак и поле ввода." A question and its answer are cards like everything else,
// joined to whatever the question was about — which is the only arrangement in which the pool's
// older sentence can be true: "выбранные в контекст объекты после отправки помещаются в рамку…
// под рамкой появляется связанный блок с результатами".
//
// The server still renders the conversation into `#blocks`, hidden. This moves each one onto the
// surface, so the answer, its state and its buttons stay exactly the markup they always were.
const blocksSource = document.getElementById('blocks');

// Which cards each question went out with, so its answer can be joined back to them. Client-side
// because it is a fact about this window's last few actions, not about the store.
const wentWith = new Map();
let lastSent = [];
// The rings still turning, oldest first: the answers arrive in the order the questions were
// asked, and this page has no better handle on which is which than that. Declared here rather
// than beside the function that fills them, because the stream can deliver a finished block
// before the rest of this file has finished running.
const ringsWaiting = [];
// And what each of those questions went out with, waiting for the block that answers it.
const awaitingBlock = [];

// What belongs to the question rather than to what came back. Three parts, listed — not "everything
// above the answer": a block whose run has produced nothing yet has no answer element for the rest
// to be above, and a rule that leant on one would put the whole exchange on the wrong card at
// exactly the moment somebody is watching it happen.
const ASKED_PARTS = '.said, .taken-as, .carried';

// One exchange, cut in two. Everything that is not the question is the answer's, so a part nobody
// thought about here lands with what came back rather than disappearing.
function halfOf(article, which) {
  const copy = article.cloneNode(true);
  copy.hidden = false;
  for (const part of [...copy.children]) {
    if (part.matches(ASKED_PARTS) !== (which === 'question')) part.remove();
  }
  return copy;
}

// The answer as a card of its own, joined to the question that produced it.
//
// "Сегодня вопрос и ответ — это один блок. Для исследования их надо разнять: к вопросу крепится
// ответ, к ответу крепится следующий вопрос, и каждое из этого — точка ветвления."
//
// One card cannot be two branch points. Following up on what was asked and following up on what
// came back are different questions, and on a single card they are the same line from the same
// box — which is how a research thread flattens back into the feed it was supposed to stop being.
function answerCard(article, rev) {
  const id = article.dataset.block;
  const name = `answer:${id}`;
  const half = halfOf(article, 'answer');
  // Nothing has come back yet. An empty card under every question is a bench of half-cards, and
  // the moment there is something to read is the moment it has earned the room.
  if (!half.children.length) return null;
  let node = surface.querySelector(`.pin[data-name="${CSS.escape(name)}"]`);
  if (!node) {
    node = document.createElement('div');
    node.className = 'pin answer-card';
    node.tabIndex = 0;
    node.dataset.kind = 'answer';
    node.dataset.id = id;
    node.dataset.name = name;
    node.dataset.view = 'hint';
    // No live dot: this one is not carried into the next message. What it says is already in the
    // thread the next message is sent with, and a card that says it is being carried when it
    // changes nothing is the guessed status of CLAUDE.md's fifth rule, in the shape of a control.
    node.innerHTML = `<div class="pin-head">
      <button type="button" class="pin-role" title="what this is in the process"></button>
      <span class="pin-kind">answered</span>
      <span class="pin-label"></span>
      <button type="button" class="pin-view" title="a line — press for what it is">a line</button>
      <button type="button" class="pin-off" title="take it off the workbench">×</button></div>
      <div class="pin-body"></div>`;
    pins.appendChild(node);
    // Under the question where there is one. A button's answer has no question card, so it is
    // placed like any other new card — and joined to nothing, because there is nothing to join it
    // to and a line to a card that is not there explains nothing.
    const asked = surface.querySelector(`.pin[data-name="block:${CSS.escape(id)}"]`);
    // Or under the two cards it was made out of, joined to both. A third card that appears in the
    // next free slot is a card nobody connects to the gesture that made it — and the gesture is
    // the whole of what "за счёт интерфейса" means.
    const mixed = (article.dataset.madeFrom || '').split(',').filter(Boolean);
    place(node, asked ? spotUnder([`block:${id}`]) : mixed.length ? spotUnder(mixed) : null);
    if (asked) ownTies.push({ from: `block:${id}`, to: name, says: 'answered' });
    else for (const one of mixed) ownTies.push({ from: one, to: name, says: 'makes' });
  }
  const body = node.querySelector('.pin-body');
  const shown = body.firstElementChild;
  if (!shown || shown.dataset.rev !== rev) {
    half.dataset.rev = rev;
    body.replaceChildren(half);
    if (window.htmx) htmx.process(body);
    settleOverlaps();
  }
  const said = node.querySelector('.answer, .stopped-what, .failure');
  node.querySelector('.pin-label').textContent =
    (said?.textContent || '').trim().slice(0, 60) || 'an answer';
  node.classList.toggle('settled', article.hasAttribute('data-settled'));
  showRole(node);
  writeHint(node);
  return node;
}

// "Как только система поймёт, к чему относится вопрос, он центрируется на этот блок, подсвечивает
// его, рисует связь к карточке вопроса и готовит ответ."
//
// The order in that sentence is its content: show what was understood, and only then answer. A
// person who can see which card their question was taken to be about has time to say "no, not that
// one" before an answer to the wrong question arrives — after it, the same information is a
// post-mortem.
//
// Centred only when it is not already on the screen. Somebody who has panned to a corner on
// purpose is looking at something, and a console that drags the surface out from under them every
// time it works something out is a console they stop asking questions on.
function sayWhatItIsAbout(cards) {
  for (const card of cards) card.classList.add('about-this');
  // One of them brought into view, and only when none of them is already there. Fitting all of
  // them on screen would zoom the surface out to hold two cards that may be a long way apart,
  // which is a worse answer to "where am I" than moving to the first of them.
  if (!cards.some(onTheScreen)) bringIntoView(cards[0]);
}

// A card for a thing that does not exist yet.
//
// "На верстаке появляются блоки что уже готово, а также неактивные/бледные блоки что сейчас в
// процессе, возможно заштрихованные с шестерёнками."
//
// The half of that which already existed is the rings a group turns while its work is running. The
// half that did not is a card standing where a thing is *going to be* — and the whole difficulty is
// that it must not be mistaken for a card standing where a thing is. A console that shows what is
// not there yet the way it shows what is there is a console that reports an inference as a fact,
// which is the fifth rule of CLAUDE.md.
//
// So a promise is marked in three ways at once, and none of them is only colour: it says
// "promised" where every other card says what it is, it is hatched, and it carries nothing into
// the next message — there is nothing to carry.
function promiseFor(id, why) {
  const name = `promise:${id}`;
  if (surface.querySelector(`.pin[data-name="${CSS.escape(name)}"]`)) return;
  const node = document.createElement('div');
  node.className = 'pin promise';
  node.tabIndex = 0;
  node.dataset.kind = 'promise';
  node.dataset.id = id;
  node.dataset.name = name;
  node.dataset.view = 'hint';
  node.innerHTML = `<div class="pin-head">
    <span class="pin-kind">promised</span>
    <span class="pin-label"></span></div>
    <div class="pin-body"><p class="small"></p></div>`;
  node.querySelector('.pin-label').textContent = why;
  node.querySelector('.pin-body p').textContent =
    'Nothing is here yet. This is where it will be when the run finishes.';
  pins.appendChild(node);
  place(node, spotUnder([`block:${id}`]));
}

function keptThePromise(id) {
  surface?.querySelector(`.pin[data-name="promise:${CSS.escape(id)}"]`)?.remove();
}

// What a message that is still running is going to put on the bench. Only the two kinds that make
// cards: a question makes an answer, which is the answer card, and there is nothing to promise
// about it that the block card is not already saying.
const PROMISES = {
  drawing: 'the cards this is drawing',
  showing: 'the cards this is fetching',
};

// Which questions have had their "follows on from" line drawn.// Which questions have had their "follows on from" line drawn. The same bookkeeping, and the same
// reason, as `arranged` below: this runs on every push and the line is drawn once.
const joined = new Set();

function syncBlocks() {
  if (!blocksSource || !surface) return;
  const current = activeThread();
  // One chat's worth. Every block ever asked is rendered into `#blocks`; putting all of them on
  // the surface at once turns it into fifty cards nobody can read, which is the thing this
  // arrangement exists to avoid.
  const mine = [...blocksSource.querySelectorAll('article.block')].filter(
    (article) => !current || article.dataset.thread === current
  );
  const wanted = new Set(mine.map((article) => `block:${article.dataset.block}`));
  for (const node of surface.querySelectorAll('.pin.block-card, .pin.answer-card')) {
    if (!wanted.has(`block:${node.dataset.id}`)) {
      placed.delete(node.dataset.name);
      node.remove();
    }
  }

  for (const article of mine) {
    const id = article.dataset.block;
    // A question a button sent has no card of its own: "как будто бы мы его вписали в поле ввода,
    // только без создания карточки запроса". The conversation shows the question like any other
    // message, and the bench shows what came back — which is the thing that was wanted.
    if (article.hasAttribute('data-by-button')) {
      answerCard(article, article.outerHTML.length.toString());
      continue;
    }
    let node = surface.querySelector(`.pin[data-name="block:${CSS.escape(id)}"]`);
    if (!node) {
      node = document.createElement('div');
      node.className = 'pin block-card';
      node.tabIndex = 0;
      node.dataset.kind = 'block';
      node.dataset.id = id;
      node.dataset.name = `block:${id}`;
      node.dataset.view = 'hint';
      node.innerHTML = `<div class="pin-head"><span class="pin-live" title="in the next message — press to leave it out">●</span>
        <button type="button" class="pin-role" title="what this is in the process"></button>
        <span class="pin-kind">asked</span>
        <span class="pin-label"></span>
        <button type="button" class="pin-view" title="a line — press for what it is">a line</button>
        <button type="button" class="pin-off" title="take it off the workbench">×</button></div>
        <div class="pin-body"></div>`;
      if (!wentWith.has(id) && awaitingBlock.length) wentWith.set(id, awaitingBlock.shift());
      // Once those copies have been collected the names no longer resolve, and the line has to
      // go to the collection instead — which is the thing on the bench that stands for them.
      wentWith.set(id, (wentWith.get(id) || []).map(nowCollected));
      pins.appendChild(node);
      // Under whatever it was about, so the answer reads as belonging to it.
      place(node, spotUnder(wentWith.get(id) || []));
      if (wentWith.has(id)) joinTo(id, wentWith.get(id));
    }
    // A *copy*, not the article itself. Moving it would empty `#blocks`, and `#blocks` is the
    // source this reads on every update — the surface would clear itself on the next pass.
    // Half a copy, now: what was asked stays here and what came back is a card of its own.
    const body = node.querySelector('.pin-body');
    const shown = body.firstElementChild;
    const rev = article.outerHTML.length.toString();
    if (!shown || shown.dataset.rev !== rev) {
      const half = halfOf(article, 'question');
      half.dataset.rev = rev;
      body.replaceChildren(half);
      if (window.htmx) htmx.process(body);
      settleOverlaps();
    }
    answerCard(article, rev);
    // A rearrangement, applied once. `data-handling` is on the answer rather than on the article,
    // because an article without an answer yet has nothing to apply.
    const asked = article.querySelector('.answer.arranged[data-handling]');
    if (asked && !arranged.has(id)) {
      arranged.add(id);
      try {
        applyArrangement(JSON.parse(asked.dataset.handling).handling || {});
      } catch {
        // An answer this page cannot read changes nothing, which is what the block already says.
      }
    }

    const said = article.querySelector('.block-input, .said, h3, p');
    node.querySelector('.pin-label').textContent =
      (said?.textContent || 'a question').trim().slice(0, 60);
    node.classList.toggle('settled', article.hasAttribute('data-settled'));
    showRole(node);
    // A block's hint is what came back, not the question again — the question is already its title.
    writeHint(node);

    // What it is going to make, while it is making it. Gone the moment the run settles, whether it
    // produced anything or not: a promise left standing over a failed run is the console saying a
    // thing is coming that is not.
    const promising = PROMISES[[...article.classList].find((one) => one in PROMISES)];
    if (promising && !article.hasAttribute('data-settled')) promiseFor(id, promising);
    else keptThePromise(id);

    // What the console read this question as following on from. Once, and only while the card it
    // names is here: `syncBlocks` runs on every push, and a line pushed each time is the same line
    // drawn forty deep by the end of a conversation.
    // One question can follow on from several cards — two parts of a thing asked about at once —
    // which is what makes an enquiry a graph rather than a tree.
    const onto = (article.dataset.relates || '')
      .split(',')
      .filter(Boolean)
      .map((name) => surface.querySelector(`.pin[data-name="${CSS.escape(name)}"]`))
      .filter(Boolean);
    if (onto.length && !joined.has(id)) {
      joined.add(id);
      // Only for a question still being worked on. A conversation the page is seeing for the first
      // time — a reload, a chat switched back to — is all settled blocks, and lighting each of them
      // in turn would drag the surface across a dozen old answers before it came to rest.
      if (!article.hasAttribute('data-settled')) sayWhatItIsAbout(onto);
      for (const card of onto) {
        ownTies.push({ from: cardName(card), to: `block:${id}`, says: 'follows on from' });
      }
      drawTies();
    }
    // The highlight lasts as long as the not-knowing does. A card still lit under a finished
    // answer says the console is still working out what the question was about.
    if (article.hasAttribute('data-settled')) {
      for (const card of onto) card.classList.remove('about-this');
    }

    // Every idea this block recorded is a card of its own, joined to it. "Если я пишу идею — на
    // верстаке появляется её карточка, и далее карточки под-идей."
    // A process this message drew. Same shape as the idea lines below: the block lists what it
    // made, and the bench puts each of them on as a card of its own.
    // Off the answer rather than off the question, because the answer is what wrote them. On the
    // question they read as things somebody asked about, which is the opposite claim.
    const from = surface.querySelector(`.pin[data-name="answer:${CSS.escape(id)}"]`)
      ? `answer:${id}`
      : `block:${id}`;
    for (const line of article.querySelectorAll('.drawn-cards li[data-kind]')) {
      const name = `${line.dataset.kind}:${line.dataset.id}`;
      if (!surface.querySelector(`.pin[data-name="${CSS.escape(name)}"]`)) {
        pin(
          { kind: line.dataset.kind, id: line.dataset.id, label: '' },
          { under: from, quiet: true, came: 'drawn from a description' }
        );
      }
    }

    for (const line of article.querySelectorAll('[data-kind="idea"][data-id]')) {
      const name = `idea:${line.dataset.id}`;
      if (!surface.querySelector(`.pin[data-name="${CSS.escape(name)}"]`)) {
        pin(
          { kind: 'idea', id: line.dataset.id, label: line.dataset.label },
          { under: from, came: 'written down by an answer' }
        );
      }
    }
  }
  emptyOrNot();
  loadTies();
}

/* --- a request that rearranges the workbench ---------------------------------------------------- */
// "Отличие от всего предыдущего в одном: результат запроса — это не новая карточка и не текст, а
// изменение того, что уже лежит."
//
// The answer arrives on its block as actions (agent_desk/handling.py) and is applied once. Applied
// once and not again is the whole of the bookkeeping here: `syncBlocks` runs on every push, and a
// rearrangement re-applied every two seconds would drag a card back from wherever somebody moved
// it to afterwards.
const arranged = new Set();

// The three a mark may be painted, and no more. Red and green are missing on purpose: on this
// board red means stopped or blocked and green means running, and a card painted one of those by a
// model would be wearing a status nothing behind it supports.
const MARK_COLOURS = ['yellow', 'blue', 'violet'];

function markCard(pin, why, colour) {
  pin.classList.add('marked');
  for (const one of MARK_COLOURS) pin.classList.toggle(`marked-${one}`, one === colour);
  let line = pin.querySelector('.pin-why');
  if (!line) {
    line = document.createElement('p');
    line.className = 'pin-why';
    pin.querySelector('.pin-head')?.after(line);
  }
  // "У каждой выбранной карточки видно, ПОЧЕМУ она выбрана… суждение показывается как суждение и
  // рядом с основанием." Without it there is an arrangement nobody can trust or argue with.
  line.textContent = why || 'picked, with no reason given';
}

function clearMarks() {
  for (const pin of surface?.querySelectorAll('.pin.marked') || []) {
    pin.classList.remove('marked', ...MARK_COLOURS.map((one) => `marked-${one}`));
    pin.querySelector('.pin-why')?.remove();
  }
}

// Where a side puts its cards. Thirds of the surface as it stands, so "справа" and "слева" mean
// what they look like rather than what a coordinate says.
function sideAt(side, index, tall) {
  const across = { left: 0, middle: 1, right: 2 }[side] ?? 1;
  return { x: 20 + across * (CARD_WIDTH + GAP * 3), y: 20 + tall };
}

function applyArrangement(said) {
  if (said.clear) clearMarks();

  // "Сверни разверни все (либо выделенные) карточки." On a bench of thirty, folding everything
  // except the four about the migration is a sentence and not thirty clicks. `setView` is the same
  // function the fold button on a card calls, so a card folded by a request and one folded by hand
  // are in the same state and neither knows which it was.
  for (const [names, view] of [
    [said.folded || [], 'hint'],
    [said.opened || [], 'metadata'],
  ]) {
    for (const name of names) {
      const pin = surface?.querySelector(`.pin[data-name="${CSS.escape(name)}"]`);
      if (pin) setView(pin, view);
    }
  }

  // "Удали карточки такие-то и такие-то" — off the surface, which is what the `×` on every card
  // already does and what undo already puts back (041). Nothing is deleted: the card is a row in
  // the store and the conversation still holds it.
  let took = 0;
  for (const name of said.taken || []) {
    const pin = surface?.querySelector(`.pin[data-name="${CSS.escape(name)}"]`);
    if (!pin) continue;
    placed.delete(name);
    pin.remove();
    took += 1;
  }
  if (took) {
    syncTargets();
    emptyOrNot();
  }

  // Last of the three that change the surface rather than a card, and last on purpose: laying the
  // bench out again after cards have come off is the arrangement somebody asked for, and doing it
  // before would leave holes where they were.
  if (said.tidy) tidyUp();
  for (const one of said.marked || []) {
    const pin = surface?.querySelector(`.pin[data-name="${CSS.escape(one.name)}"]`);
    if (pin) markCard(pin, one.why, one.colour);
  }

  // Every height read before any card moves — placing one changes the layout the next measurement
  // would be answered from.
  const columns = (said.sorted || []).filter((one) => one.names.length);
  if (!columns.length) {
    // Folding changes every card's height, so the ones below have to be let down again. Taking
    // cards off changes the surface itself, so the lines and the map are redrawn and the layout
    // is written down — otherwise a bench reloaded a minute later has them back.
    if (!said.tidy && ((said.folded || []).length || (said.opened || []).length)) {
      settleOverlaps();
    }
    if (took) {
      rememberLayout();
      drawTies();
      drawMap();
    }
    return;
  }
  const tall = new Map();
  for (const one of columns) {
    for (const name of one.names) {
      const pin = surface?.querySelector(`.pin[data-name="${CSS.escape(name)}"]`);
      if (pin) tall.set(pin, pin.offsetHeight || 120);
    }
  }
  const down = new Map();
  for (const one of columns) {
    // "Здесь же — колонкам нужны заголовки, иначе через минуту непонятно, что слева, а что справа."
    down.set(one.side, (down.get(one.side) ?? 0) + 0);
    for (const [at, name] of one.names.entries()) {
      const pin = surface?.querySelector(`.pin[data-name="${CSS.escape(name)}"]`);
      if (!pin) continue;
      const y = down.get(one.side) ?? 0;
      place(pin, sideAt(one.side, at, y), { avoid: false });
      // Sorted by hand in the sense that matters: somebody asked for this arrangement, so the
      // console's own layout must not sweep it away (042-placed-by-hand.sql).
      pin.dataset.moved = 'yes';
      down.set(one.side, y + tall.get(pin) + GAP);
      markCard(pin, one.what);
    }
  }
  moveWasDeliberate();
  drawTies();
  drawMap();
}

// A copy that has since been collected answers to its collection's name. Before this the line
// from an answer pointed at four nodes that no longer existed, and simply was not drawn.
function nowCollected(name) {
  if (surface?.querySelector(`.pin[data-name="${CSS.escape(name)}"]`)) return name;
  const group = name.match(/^held(\d+)-/);
  return group ? `group:g${group[1]}` : name;
}

// Where a new card goes when it belongs under others: below the lowest of them, roughly centred.
function spotUnder(names) {
  const spots = names.map((name) => placed.get(name)).filter(Boolean);
  if (!spots.length) return null;
  const left = Math.round(spots.reduce((sum, at) => sum + at.x, 0) / spots.length);
  const lowest = Math.max(...spots.map((at) => at.y));
  return { x: left, y: lowest + 260 };
}

// Lines from a block to the cards it went out with. Held on the page rather than asked of the
// server: the server has no idea what was on somebody's workbench when they pressed send.
const ownTies = [];

function joinTo(blockId, names) {
  for (const name of names) {
    ownTies.push({ from: name, to: `block:${blockId}`, says: 'asked about' });
  }
  drawTies();
}

function emptyOrNot() {
  const anything = surface?.querySelectorAll('.pin').length;
  document.getElementById('bench-canvas')?.classList.toggle('is-empty', !anything);
}

/* --- what is charged, and what is only sitting there ------------------------------------------- */
// "При перемещении на верстак объект сразу заряжается (значит будет участвовать в контексте),
// одиночное нажатие снимает подсветку и отменяет участие в текущем контексте, повторное нажатие
// активирует обратно."
//
// A card that landed here is in the message: that is what dropping it meant, and making somebody
// then confirm it would be asking twice. What was missing is the way *out* without dragging it
// away — you want to see a card and not send it, which is a different thing from not wanting it
// on the bench at all.
document.addEventListener('click', (event) => {
  const holder = event.target.closest('.pin');
  if (!holder) return;
  if (event.target.closest('button, a, textarea, input, select')) return;
  // A drag that ended on this card is not a press on it.
  if (justDragged) {
    justDragged = false;
    return;
  }
  // Shift-clicking is the same act and is handled where the band is, so that adding one card and
  // sweeping several are one piece of code with one meaning.
  if (event.shiftKey) return;

  // The dot is the other direction, and it works under every tool: leave *this* one out while the
  // rest still go. Two different sentences, so two different controls.
  if (event.target.closest('.pin-live')) {
    holder.classList.toggle('spent');
    syncTargets();
    drawMap();
    return;
  }

  // "Если я один раз кликаю на карточку ЛКМ — она начинает светиться и только она будет
  // участвовать в следующем запросе, повторный клик убирает её из запроса."
  //
  // Under the Choose tool, and not under Move. A click that sometimes opens a card and sometimes
  // changes what the next question is about is a click nobody can predict, and the tool strip is
  // what makes the difference visible before the press rather than after it.
  //
  // The default is everything: a card is on the bench because somebody put it there, and making
  // them confirm each one would be asking twice. Choosing narrows that to what was chosen, and
  // choosing nothing is back to everything — so the gesture has no state to get stuck in.
  if (tool !== 'choose') return;
  holder.classList.toggle('chosen');
  showChosen();
});

/* --- a block of your own on the workbench ----------------------------------------------------- */
// "ПКМ в рабочем пространстве — можно добавить временный блок; блок может содержать
// ссылки/документы/просто текст или кусок кода."
//
// A button rather than the right mouse button. Overriding the browser's own context menu takes
// away paste, open-in-new-tab and inspect from somebody who was reaching for them, and this is a
// window people paste *into* all day — the one gesture worth least is the one that costs that.
//
// Temporary is the whole of it: this block lives in the page, travels with the next message as
// context like every other card on the bench, and is gone when the tab is. Nothing is stored,
// because a note that outlived the question it was written for would be a second idea pool
// nobody asked for (docs/05-ideas.md).
let ownBlocks = 0;

function addOwnBlock(kind = 'note') {
  const said = {
    note: {
      label: 'a note',
      placeholder:
        'Anything: a paragraph, a decision, a snippet of code. It goes with the next message and is gone when this tab is.',
    },
    link: {
      label: 'a link',
      placeholder: 'https://… — paste the address, and anything about it worth saying.',
    },
    file: {
      label: 'a file',
      placeholder:
        'The path to a file on this machine, and what matters about it. Nothing is uploaded — the path is what travels, and whoever reads it has to be able to open it.',
    },
  }[kind];

  const holder = document.createElement('div');
  holder.className = 'pin own';
  holder.tabIndex = 0;
  holder.dataset.kind = 'note';
  holder.dataset.id = `note-${++ownBlocks}`;
  holder.dataset.name = `note:${holder.dataset.id}`;
  holder.dataset.deep = 'no';
  holder.dataset.view = 'hint';
  holder.innerHTML = `<div class="pin-head"><button type="button" class="pin-role" title="what this is in the process"></button>
    <span class="pin-kind">${kind}</span>
    <span class="pin-label">${said.label}</span>
    <button type="button" class="pin-view" title="a line — press for what it is">a line</button>
    <button type="button" class="pin-off" title="take it off the workbench">×</button></div>
    <div class="pin-body"><textarea class="own-text" rows="4"
      placeholder="${said.placeholder}"></textarea></div>`;
  pins.appendChild(holder);
  place(holder);
  syncTargets();
  holder.querySelector('.own-text').focus();
}

document.addEventListener('click', (event) => {
  if (event.target.closest('[data-add-note]')) {
    event.preventDefault();
    addOwnBlock();
  }
});

// What is typed into one travels with the message, in the same field the pinned cards use.
function ownBlockText() {
  return [...pins.querySelectorAll('.pin.own:not(.spent):not(.ringed) .own-text')]
    .map((field) => field.value.trim())
    .filter(Boolean)
    .join('\n\n---\n\n');
}

/* --- plain words, and the technical half behind a toggle ---------------------------------------- */
// A card dropped on the workbench opens in plain words: a card that leads with paths and pids is a
// card only a programmer can use, and this board is meant to be readable by whoever is looking at
// it. The details are real and useful and one press away (docs/06-console.md).
document.addEventListener('click', (event) => {
  const button = event.target.closest('[data-detail-toggle]');
  if (!button) return;
  const card = button.closest('[data-detail]');
  if (!card) return;
  const technical = card.dataset.detail !== 'technical';
  card.dataset.detail = technical ? 'technical' : 'plain';
  button.setAttribute('aria-pressed', String(technical));
  button.textContent = technical ? 'plain words' : 'technical details';
  // `hidden` rather than a style, so a card with no script still shows the plain half and nothing
  // is stuck invisible.
  card.querySelector('.plain-only').hidden = technical;
  card.querySelector('.technical-only').hidden = !technical;
});

/* --- go to it ---------------------------------------------------------------------------------- */
// A page cannot open a terminal on somebody's desktop, and a button that claimed to would be one
// more thing on this board that says something it does not know. What it can do is hand over the
// exact line, so that going there is a paste rather than a hunt for the id.
document.addEventListener('click', async (event) => {
  const button = event.target.closest('[data-copy]');
  if (!button) return;
  event.preventDefault();
  const said = button.textContent;
  try {
    await navigator.clipboard.writeText(button.dataset.copy);
    button.textContent = '✓ copied — paste it in a terminal';
  } catch {
    // No clipboard (an insecure context, a browser that refuses): show the line instead of
    // pretending it was copied.
    button.textContent = button.dataset.copy;
    return;
  }
  setTimeout(() => { button.textContent = said; }, 2000);
});

/* --- the keyboard ----------------------------------------------------------------------------- */
// This window hovers over a terminal, and reaching for the mouse is what it exists to save.
document.addEventListener('keydown', (event) => {
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName);
  if (event.key === '/' && !typing) {
    event.preventDefault();
    document.getElementById('ask-text').focus();
  }
  // Ctrl+Z, which is what somebody presses without being told. Not while typing: in a field it
  // has to undo the typing, and a shortcut that ate a paragraph to move a card would be worse
  // than not having one.
  if (event.key.toLowerCase() === 'z' && (event.ctrlKey || event.metaKey) && !typing) {
    event.preventDefault();
    undoBench();
    return;
  }

  // Ctrl+L clears a terminal; here it folds the conversation up out of the way and leaves the
  // field where it was. Pressing it again brings the conversation back.
  if (event.key === 'l' && (event.ctrlKey || event.metaKey)) {
    event.preventDefault();
    // Ctrl+L in a terminal clears the scrollback. Here it folds the conversation away and back:
    // "весь чат сворачивается вверх, как в консоли, но с возможностью развернуть обратно" —
    // folding rather than clearing, because a fold loses nothing.
    //
    // Clearing the workbench is a different act and keeps a place of its own: Shift does it, and
    // the right mouse button offers it by name.
    if (event.shiftKey) clearBench();
    else foldConversation();
    document.getElementById('ask-text').focus();
    return;
  }

  if (event.key === 'Escape') {
    const panel = document.getElementById('message');
    if (panel.innerHTML.trim()) panel.innerHTML = '';
    else if (pins.children.length) clearBench();
    else document.activeElement.blur();
  }

  // The rest of them, and every one is a thing this window makes somebody reach for the mouse to
  // do. Nothing here fires while somebody is typing, and nothing here is destructive: the two
  // rules that keep a keyboard shortcut from being a trap.
  if (typing || event.ctrlKey || event.metaKey || event.altKey) return;

  // `i` puts the cursor in the field with /idea already typed, which is the second most common
  // thing anybody does here after asking a question.
  if (event.key === 'i') {
    event.preventDefault();
    const field = document.getElementById('ask-text');
    if (!field.value.trim()) field.value = '/idea ';
    field.focus();
    field.setSelectionRange(field.value.length, field.value.length);
    return;
  }

  // The three columns, by number: hide one, show it again. The same buttons the rails press.
  const column = { 1: 'overview', 2: 'blockers', 3: 'right' }[event.key];
  if (column) {
    event.preventDefault();
    const button = document.querySelector(`[data-hide="${column}"]`)
      || document.querySelector(`[data-show="${column}"]`);
    if (button) button.click();
    return;
  }

  // `n` opens a new chat and `w` closes the one that is open — a browser's own two, because this
  // page is a set of tabs and somebody who uses tabs already knows these.
  if (event.key === 'n') {
    const plus = document.querySelector('.tab-new button');
    if (plus) { event.preventDefault(); plus.click(); }
    return;
  }
  if (event.key === 'w') {
    const close = document.querySelector('.tab.on .tab-off');
    if (close) { event.preventDefault(); close.click(); }
    return;
  }

  // `?` says what all of this is, because a shortcut nobody can discover is a shortcut nobody
  // uses. It is the same panel every other card opens into.
  if (event.key === '?') {
    event.preventDefault();
    document.getElementById('message').innerHTML = KEYS;
  }
});

/* --- everything on this page, from one field --------------------------------------------------- */
// A console with three columns, six kinds of card and a dozen buttons has a discovery problem that
// more buttons do not solve. Ctrl+K is the answer every tool of this shape converged on: type a
// few letters, get the thing, press Enter.
//
// It searches what is already rendered rather than asking the server. That is not a shortcut — it
// is the correct source: the page holds every project, session, idea and blocker the board is
// currently showing, with the same words on them that somebody just read. A palette that searched
// a different set from the one on screen would be a palette that disagrees with the page.
const PALETTE_ROWS = [
  ['.idea-card', 'idea'],
  ['.card.blocker.node', 'blocker'],
  ['[data-kind="session"]', 'session'],
  ['[data-kind="project"]', 'project'],
  ['[data-kind="instance"]', 'checkout'],
];

let palette = null;
let paletteAt = 0;

function everythingOnThePage() {
  const found = [];
  const seen = new Set();
  for (const [where, kind] of PALETTE_ROWS) {
    for (const node of document.querySelectorAll(where)) {
      const id = node.dataset.id || node.dataset.label || '';
      const name = (node.dataset.label || node.querySelector('.card-name')?.textContent || '').trim();
      if (!name || seen.has(`${kind}:${id}`)) continue;
      seen.add(`${kind}:${id}`);
      found.push({ kind, id, name, node });
    }
  }
  return found;
}

function openPalette() {
  if (palette) return closePalette();
  palette = document.createElement('div');
  palette.className = 'palette';
  palette.innerHTML = `<div class="palette-box">
    <input type="text" class="palette-field" placeholder="undo, lay it out again, a project, a session, an idea…"
           autocomplete="off" spellcheck="false" aria-label="do anything, or find anything on this board">
    <ul class="palette-list"></ul>
    <p class="palette-foot">Enter does it, or puts it on the workbench · Esc closes</p>
  </div>`;
  document.body.appendChild(palette);
  const field = palette.querySelector('.palette-field');
  field.addEventListener('input', () => drawPalette(field.value));
  field.addEventListener('keydown', paletteKeys);
  palette.addEventListener('pointerdown', (event) => {
    if (event.target === palette) closePalette();
  });
  drawPalette('');
  field.focus();
}

function closePalette() {
  palette?.remove();
  palette = null;
  paletteAt = 0;
}

// Every word has to appear somewhere in the name, in any order. Not a fuzzy match: on a list this
// short a fuzzy match mostly produces confident wrong answers, and "api sess" finding the session
// in api is the whole of what somebody wants from it.
// Everything the console can *do*, read off the page rather than listed here.
//
// "Ctrl+K сегодня ищет карточки. Жестов стало столько, что нужен и второй режим: не «найди вещь»,
// а «сделай действие» — соединить, раскрыть, запустить, разложить, сохранить как процесс."
//
// One door rather than a second shortcut: somebody who has to remember which of two palettes holds
// the thing they want has been given a filing problem instead of a keyboard. Typing "undo" finds
// the action, typing "duck" finds the project, and the row says which it is.
//
// **Gathered from the controls themselves.** A hand-written list of what the console can do is a
// list that falls behind the day somebody adds a button — and this idea is precisely "everything
// the console can do", so a list that can be incomplete answers the wrong question. These are the
// two places a control that acts on the workbench lives, so anything added to either is in the
// palette on the same commit, without being mentioned twice.
const ACTION_BARS = ['.bench-head', '#bench-menu'];

function everyAction() {
  const seen = new Set();
  const actions = [];
  for (const bar of ACTION_BARS) {
    for (const button of document.querySelectorAll(`${bar} button`)) {
      // The dots for cards that are off the screen live in the bench head, and each is a way to
      // reach one card rather than a thing the console can do. Thirty of them fill the palette
      // with the card list it already has, under worse names.
      if (button.closest('#off-edge')) continue;
      // A control with no words is a control nobody can ask for by name. The zoom's `−` and `+`
      // are the honest example: "smaller" is their aria-label, and that is what to type.
      const what = (button.getAttribute('aria-label') || button.textContent || '').trim();
      if (!what || seen.has(what)) continue;
      seen.add(what);
      actions.push({ kind: 'do', name: what, why: button.title || '', button });
    }
  }
  return actions;
}

function paletteMatches(said) {
  const words = said.toLowerCase().split(/\s+/).filter(Boolean);
  const fits = (one, against) => words.every((word) => against.toLowerCase().includes(word));
  // Actions first. With nothing typed the question is "what can I do", and with something typed a
  // word that names an action almost always means the action — "undo" is not a card.
  const doing = everyAction().filter((one) => fits(one, `${one.name} ${one.why}`));
  const things = everythingOnThePage().filter((one) => fits(one, `${one.kind} ${one.name}`));
  return [...doing, ...things].slice(0, 12);
}

function drawPalette(said) {
  const list = palette?.querySelector('.palette-list');
  if (!list) return;
  const rows = paletteMatches(said);
  paletteAt = Math.min(paletteAt, Math.max(0, rows.length - 1));
  list.replaceChildren();
  if (!rows.length) {
    const empty = document.createElement('li');
    empty.className = 'palette-empty';
    empty.textContent = 'nothing on the board matches that';
    list.appendChild(empty);
    return;
  }
  rows.forEach((one, index) => {
    const row = document.createElement('li');
    row.className = `palette-row${index === paletteAt ? ' at' : ''}`;
    row.innerHTML = '<span class="palette-kind"></span><span class="palette-name"></span>';
    row.querySelector('.palette-kind').textContent = one.kind;
    row.querySelector('.palette-name').textContent = one.name;
    // What the button's tooltip says, for the actions whose name is a word ("map", "fold").
    if (one.why) row.title = one.why;
    row.addEventListener('pointerdown', () => takePalette(one));
    list.appendChild(row);
  });
}

function paletteKeys(event) {
  const rows = paletteMatches(event.target.value);
  if (event.key === 'Escape') {
    event.preventDefault();
    closePalette();
  } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault();
    paletteAt = Math.max(0, Math.min(rows.length - 1, paletteAt + (event.key === 'ArrowDown' ? 1 : -1)));
    drawPalette(event.target.value);
  } else if (event.key === 'Enter' && rows[paletteAt]) {
    event.preventDefault();
    takePalette(rows[paletteAt]);
  }
}

// What choosing one does: it lands on the workbench, which is where everything on this page goes
// to be looked at and asked about. Not "scroll the column to it" — that is a different tool's
// answer, and this one has a surface.
function takePalette(one) {
  closePalette();
  // An action is done by pressing the control it was read off, rather than by calling the function
  // behind it: one path, so the palette cannot do a thing differently from the button for it.
  if (one.button) {
    one.button.click();
    return;
  }
  pin(
    { kind: one.kind === 'checkout' ? 'instance' : one.kind, id: one.id, label: one.name },
    { came: 'found with Ctrl+K' }
  );
}

document.addEventListener('keydown', (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
    event.preventDefault();
    openPalette();
  }
});

// Written here rather than in a template: it is a list of what this file does, and a copy in a
// template is a copy that stops being true.
const KEYS = `<div class="keys card"><div class="card-head"><span class="card-name">the keyboard</span></div>
<div class="card-body"><dl>
<dt>/</dt><dd>ask something</dd>
<dt>i</dt><dd>write an idea down</dd>
<dt>Ctrl+L</dt><dd>fold the conversation away, and back</dd>
<dt>1 · 2 · 3</dt><dd>hide the overview, the blockers, the right column — press again to bring it back</dd>
<dt>n · w</dt><dd>a new chat, and close this one</dd>
<dt>Esc</dt><dd>close this panel, then clear the workbench, then let go of the field</dd>
<dt>m</dt><dd>the map of the whole workbench</dd>
<dt>Shift+drag</dt><dd>choose several cards at once — then one press acts on all of them</dd>
<dt>Ctrl+A</dt><dd>choose every card on the workbench</dd>
<dt>Ctrl+K</dt><dd>find any project, session, idea or blocker and put it on the workbench</dd>
<dt>← ↑ → ↓</dt><dd>move the card you have chosen — with nothing chosen, move the bench itself</dd>
<dt>?</dt><dd>this</dd>
</dl></div></div>`;

// What a question is asked with, and what is left behind once it has been answered.
//
// The model somebody asked for, and it is not the one this had: **a card stays active until you
// switch it off.** Sending used to spend every card that went — the bench was cleared of context
// by the act of asking, so a follow-up question about the same four cards meant dragging them
// back. Active is now a standing state of the card, and clicking it is the only thing that
// changes it: "если активна — следующий запрос собирает в одну группу все активные карточки".
//
// So the group that goes out is made of **copies**. The originals stay where they are, still
// active, ready for the next question; the copies are a snapshot of what this one was asked with,
// and nothing that happens to the bench afterwards can rewrite it. That is the whole reason for
// copying rather than framing in place — a record made of the live cards is a record that changes
// when somebody moves one.
document.getElementById('ask').addEventListener('submit', () => {
  document.getElementById('say-notes').value = ownBlockText();
  document.getElementById('say-targets').value = pinnedTargets();
  document.getElementById('say-history').value = attachedBlocks();
  lastSent = activeCards().map(cardName);
  ringWhatWentWithIt();
  // And where it went. `ringWhatWentWithIt` has just placed the copies below everything, which on
  // a bench of forty cards is off the bottom of the window.
  const ring = surface?.querySelector('.ring.working:last-of-type');
  bringTheseIntoView((ring?.dataset.holds || '').split(',').filter(Boolean));
});

function activeCards() {
  // Not a copy of an earlier question, and not something already inside a ring: those are the
  // record, and a record that took part in the next question would grow by reading itself.
  return [...pins.querySelectorAll('.pin:not(.spent):not(.ringed):not(.put-away)[data-kind]')];
}

// Where a snapshot goes: clear of everything already on the bench, so it does not land on top of
// the cards it is a copy of.
function belowEverything() {
  const all = [...placed.values()];
  if (!all.length) return { x: 20, y: 20 };
  return { x: 20, y: Math.max(...all.map((at) => at.y)) + 260 };
}

// How tall a folded card is, near enough to lay a block of them out before any of them has been
// measured. Exact would mean reading the height of a card that is still being built.
const FOLDED_HIGH = 64;

let groups = 0;

function ringWhatWentWithIt() {
  const went = activeCards();
  if (!went.length) return;

  const at = belowEverything();
  const held = [];
  went.forEach((original, index) => {
    const copy = original.cloneNode(true);
    // A name of its own. Two nodes answering to `session:abc` would have the layout, the ties and
    // the targets all picking whichever the browser returned first.
    copy.dataset.name = `held${groups}-${index}:${cardName(original)}`;
    copy.dataset.of = cardName(original);
    copy.classList.add('copy', 'ringed');
    copy.classList.remove('moving');
    setView(copy, 'hint');
    pins.appendChild(copy);
    // In a block, roughly square. A row is what a group of four folded cards wants to be and what
    // a group of sixty cannot be: sixty in a line is seventeen thousand pixels, which is not a
    // shape any zoom can show — the smallest this console has still put twelve of them on screen.
    // Found by bringing the group into view and watching it arrive as a sliver.
    const across = Math.min(8, Math.ceil(Math.sqrt(went.length)));
    place(
      copy,
      {
        x: at.x + (index % across) * (CARD_WIDTH + GAP),
        y: at.y + Math.floor(index / across) * (FOLDED_HIGH + GAP),
      },
      { avoid: false }
    );
    held.push(copy.dataset.name);
  });

  // A frame *around* them, not a box they are moved into: on a surface, re-parenting a card would
  // take its position with it. The frame is drawn from where the cards are and redrawn when they
  // move, which is the same rule the lines follow.
  const ring = document.createElement('div');
  ring.className = 'ring working';
  ring.innerHTML = '<span class="ring-gear" aria-hidden="true">⚙</span>';
  ring.dataset.holds = held.join(',');
  ring.dataset.of = went.map(cardName).join(',');
  ring.dataset.group = String(groups);
  groups += 1;
  surface.appendChild(ring);
  ringsWaiting.push(ring);
  // What this question went out with, waiting for the block that answers it.
  awaitingBlock.push(held);
  syncTargets();
  drawRings();
}

// Every ring, sized to what it holds. Called whenever anything moves, for the same reason the
// lines are: a frame that stays where the cards used to be is worse than no frame.
function drawRings() {
  for (const ring of surface?.querySelectorAll('.ring') || []) {
    const held = (ring.dataset.holds || '')
      .split(',')
      .map((name) => ({ at: placed.get(name), el: surface.querySelector(`.pin[data-name="${CSS.escape(name)}"]`) }))
      .filter((one) => one.at && one.el);
    if (!held.length) {
      ring.hidden = true;
      continue;
    }
    ring.hidden = false;
    const pad = 14;
    const left = Math.min(...held.map((one) => one.at.x)) - pad;
    const top = Math.min(...held.map((one) => one.at.y)) - pad;
    const right = Math.max(...held.map((one) => one.at.x + one.el.offsetWidth)) + pad;
    const bottom = Math.max(...held.map((one) => one.at.y + one.el.offsetHeight)) + pad;
    ring.style.left = `${left}px`;
    ring.style.top = `${top}px`;
    ring.style.width = `${right - left}px`;
    ring.style.height = `${bottom - top}px`;
  }
}

// The answer landed, so the frame stops being a frame and becomes a thing.
//
// "Та общая обводка после исполнения должна становиться отдельной цельной собирательной карточкой
// на верстаке со своими взаимосвязями и блоками вывода." A hatched outline around four copies is
// the right picture of work in progress and the wrong picture of work that is finished: it takes
// four cards' worth of bench to say one thing that happened. So it collapses into one card that
// holds what went in, and keeps its lines to the originals and to the answer.
function ringDone() {
  const ring = ringsWaiting.shift();
  if (!ring) return;
  ring.classList.remove('working');
  collect(ring);
}

function collect(ring) {
  const held = (ring.dataset.holds || '').split(',').filter(Boolean);
  const copies = held
    .map((name) => surface.querySelector(`.pin[data-name="${CSS.escape(name)}"]`))
    .filter(Boolean);
  if (!copies.length) {
    ring.remove();
    return;
  }

  const at = placed.get(held[0]) || belowEverything();
  const id = `g${ring.dataset.group}`;
  const card = document.createElement('div');
  card.className = 'pin collection';
  card.dataset.kind = 'group';
  card.dataset.id = id;
  card.dataset.name = `group:${id}`;
  card.dataset.view = 'hint';
  // A collection is a record, not context. It is not carried into the next question — the cards
  // it holds are still on the bench for that, and sending a question its own transcript back is
  // how a conversation starts talking about itself.
  card.classList.add('ringed');
  card.tabIndex = 0;
  card.innerHTML = `<div class="pin-head"><button type="button" class="pin-role" title="what this is in the process"></button>
    <span class="pin-kind">asked with</span>
    <span class="pin-label"></span>
    <button type="button" class="pin-view" title="a line — press for what it is">a line</button>
    <button type="button" class="pin-off" title="take it off the workbench">×</button></div>
    <p class="pin-hint"></p>
    <div class="pin-body"><ul class="collected"></ul></div>`;
  card.querySelector('.pin-label').textContent =
    `${copies.length} card${copies.length === 1 ? '' : 's'}`;
  card.querySelector('.pin-hint').textContent = copies
    .map((copy) => copy.querySelector('.pin-label')?.textContent?.trim() || 'a card')
    .join(' · ');

  const list = card.querySelector('.collected');
  for (const copy of copies) {
    const row = document.createElement('li');
    row.innerHTML = '<span class="collected-kind"></span><span class="collected-name"></span>';
    row.querySelector('.collected-kind').textContent = copy.dataset.kind || '';
    row.querySelector('.collected-name').textContent =
      copy.querySelector('.pin-label')?.textContent?.trim() || copy.dataset.id || '';
    // What it takes to put this card back. "Группа, ушедшая в запрос, сворачивается в одну
    // карточку — и разложить её обратно нельзя. А это ровно то, что захочется сделать, чтобы
    // повторить вопрос с одной изменённой карточкой." The row was a name and a kind for reading;
    // these three are the same three things `pin` needs, so the list is now the record *and* the
    // way back rather than a description of one.
    row.dataset.kind = copy.dataset.kind || '';
    row.dataset.id = copy.dataset.id || '';
    row.dataset.label = copy.querySelector('.pin-label')?.textContent?.trim() || '';
    list.appendChild(row);
    placed.delete(copy.dataset.name);
    copy.remove();
  }

  pins.appendChild(card);
  showRole(card);
  place(card, at, { avoid: false });

  // Its own relations. To each card it was asked with, where that card is still on the bench —
  // which is the line that says "this is what happened to those" — and the answer joins itself
  // when its block arrives, through the same `wentWith` the block cards already use.
  for (const name of (ring.dataset.of || '').split(',').filter(Boolean)) {
    if (surface.querySelector(`.pin[data-name="${CSS.escape(name)}"]`)) {
      ownTies.push({ from: name, to: `group:${id}`, says: 'asked about' });
    }
  }
  ring.remove();
  syncTargets();
  drawTies();
  drawRings();
}

applyFolded();
applyTabOrder();

/* --- and the first paint ----------------------------------------------------------------------- */
// Everything above defines how the surface behaves; this is what puts the workbench and the
// conversation on it when the page opens, rather than only when the next event arrives.
//
// The bench before the conversation, and that order is load-bearing twice. `syncBlocks` draws a
// card for every idea a block recorded, so a restore that ran after it would draw a second one of
// each; and nothing is written back to the store until `restoreBench` has said the surface is
// whole, which is what stops the empty surface of the first millisecond being saved over the
// bench somebody left.
restoreBench();
showActiveThread();
emptyOrNot();
// Once at the start, because the first board push may be two seconds away and an empty line where
// a count belongs reads as a broken panel rather than as one that has not answered yet.
readRoom();
// And the kept tools, which live beside the projects rather than in a menu: a list nobody opened
// is a list nobody remembers they have (065-a-tool-you-keep.sql).
showTools();
