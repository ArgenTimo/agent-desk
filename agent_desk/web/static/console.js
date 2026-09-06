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
  // The workbench belongs to the chat: switching to another one starts with its own surface,
  // and `showActiveThread` puts that chat's conversation back on it.
  clearBench();
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
    clearBench();
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

function pinnedTargets() {
  // A note is not a card the server can look up — it is text that exists only here — so it is
  // carried in its own field rather than named as a target that would 404.
  return [...pins.querySelectorAll('[data-kind]:not(.own):not(.spent):not(.ringed)')]
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
  const live = pins.querySelectorAll('.pin:not(.spent):not(.ringed)').length;
  const carried = live + attached;
  const deep = pins.querySelectorAll('.pin.deep').length;
  document.getElementById('context-count').textContent = carried
    ? `carrying ${live} card${live === 1 ? '' : 's'}` +
      `${deep ? ` (${deep} in full)` : ''}` +
      `${attached ? ` and ${attached} earlier answer${attached === 1 ? '' : 's'}` : ''}`
    : '';
  document.querySelector('.context-strip').classList.toggle('on', carried > 0);
  // One idea on the workbench means one obvious next move, so the console offers it rather than
  // waiting to be told in words it already knows.
  const ideas = pins.querySelectorAll('[data-kind="idea"]:not(.spent):not(.ringed)').length;
  const go = document.getElementById('get-started');
  go.hidden = ideas === 0;
  go.textContent = ideas > 1 ? `Get started on these ${ideas}` : 'Get started on it';
  showActiveThread();
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

document.getElementById('clear-context').addEventListener('click', clearBench);

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
        { at: { x: at.x - CARD_WIDTH - GAP * 3, y: at.y }, quiet: true }
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
          { at: { x: at.x + depth * (CARD_WIDTH + GAP * 2), y: at.y + brought * 40 }, quiet: true }
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
  holder.innerHTML = `<div class="pin-head"><span class="pin-live" title="in the next message — press to leave it out">●</span>
    <button type="button" class="pin-role" title="what this is in the process"></button>
    <span class="pin-kind">${card.kind}</span>
    <span class="pin-label"></span>
    <button type="button" class="pin-view" title="a line — press for what it is">a line</button>
    <button type="button" class="pin-deep" title="send its whole transcript, not just the summary">brief</button>
    <button type="button" class="pin-off" title="stop talking about this">×</button></div>
    <div class="pin-body">reading…</div>`;
  holder.querySelector('.pin-label').textContent = card.label || card.id;
  pins.appendChild(holder);
  showRole(holder);
  place(holder, how?.under ? spotUnder([`block:${how.under}`]) : how?.at || null);
  if (how?.under) ownTies.push({ from: `block:${how.under}`, to: cardName(holder), says: 'wrote' });
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
    writeHint(holder);
    settleOverlaps();
  } catch {
    holder.querySelector('.pin-body').innerHTML = '<p class="empty small">could not read this one</p>';
  }
  syncTargets();
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
function markHintCounts(holder) {
  const name = holder.dataset.name;
  const joined = everyTie().filter((tie) => tie.from === name || tie.to === name).length;
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
  pin({ kind: card.dataset.kind, id: card.dataset.id, label: card.dataset.label });
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
    if (!dragged.fromPins) pin(dragged);
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

const PLACED = 'agent-desk:bench-layout';
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
function cardName(pin) {
  return pin.dataset.name || `${pin.dataset.kind}:${pin.dataset.id}`;
}

function rememberLayout() {
  try {
    localStorage.setItem(PLACED, JSON.stringify([...placed.entries()]));
  } catch {
    // A window that will not remember where things were still lets you move them.
  }
}

function recallLayout() {
  try {
    const said = localStorage.getItem(PLACED);
    placed = new Map(said ? JSON.parse(said) : []);
  } catch {
    placed = new Map();
  }
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
// every card on the bench into localStorage — synchronously, at the rate the pointer reports,
// which on a fast mouse is over a hundred times a second, with the tie and ring geometry rebuilt
// alongside it. That is the stutter. The layout is now written once, when the card is let go.
//
// **A card with no remembered position started from 0,0** and jumped to the corner on the first
// touch. Where it actually is on screen is a better answer than the origin.
let moving = null;

// What may be grabbed, and what is somebody trying to press or read instead.
const NOT_A_GRIP =
  'button, a, input, textarea, select, summary, details, option, label, .pin-live, .pin-role';

function gripOf(target) {
  if (target.closest(NOT_A_GRIP)) return null;
  const pin = target.closest('.pin');
  if (!pin) return null;
  // A folded card is a handle all over. An opened one is text, so it keeps its head.
  if (target.closest('.pin-head')) return pin;
  return pin.dataset.view === 'hint' ? pin : null;
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
  if (!event.target.closest('.pin')) {
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
    drawTies();
    drawRings();
    // Once, here, rather than on every event of the drag.
    if (wasACard) rememberLayout();
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
  const bar = document.getElementById('chosen-bar');
  if (!bar) return;
  const many = chosenCards();
  bar.hidden = many.length < 2;
  const says = bar.querySelector('.chosen-count');
  if (says) says.textContent = `${many.length} chosen`;
}

canvas?.addEventListener('pointerdown', (event) => {
  if (event.button !== 0 || !event.shiftKey) return;
  if (event.target.closest('.pin')) return;
  event.preventDefault();
  const frame = surface.getBoundingClientRect();
  band = {
    from: { x: (event.clientX - frame.left) / view.scale, y: (event.clientY - frame.top) / view.scale },
    box: document.createElement('div'),
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
  band.box.remove();
  band = null;
  if (!at) return;
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

window.addEventListener('pointerup', endBand);
window.addEventListener('pointercancel', endBand);

// A press on bare surface that did not become a pan is somebody clearing the selection, which is
// what clicking away means everywhere else.
canvas?.addEventListener('click', (event) => {
  if (event.target.closest('.pin, .ring, #bench-menu, #chosen-bar')) return;
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
  if (!spots.length) {
    mapBox.replaceChildren();
    return;
  }
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
    await pin({ kind: one.kind, id: one.id, label: one.label }, { at: one.at, quiet: true });
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

async function readRoles() {
  try {
    const answer = await fetch('/cards/roles');
    if (!answer.ok) return;
    const said = await answer.json();
    roleSays = said.says || {};
    roleNaturally = said.naturally || {};
    roleChosen = said.roles || {};
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
    .filter(
      (line) =>
        surface?.querySelector(`.pin[data-name="${CSS.escape(line.from)}"]`) &&
        surface?.querySelector(`.pin[data-name="${CSS.escape(line.to)}"]`)
    )
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
  const body = new URLSearchParams({ from, to, kind, says });
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
    await fetch('/workbench/untie', { method: 'POST', headers: FORM, body: new URLSearchParams({ id }) });
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

canvas?.addEventListener(
  'wheel',
  (event) => {
    if (!event.ctrlKey) return;
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

function drawTies() {
  if (!ties) return;
  ties.textContent = '';
  let drew = 0;
  for (const tie of everyTie()) {
    const one = surface.querySelector(`.pin[data-name="${CSS.escape(tie.from)}"]`);
    const other = surface.querySelector(`.pin[data-name="${CSS.escape(tie.to)}"]`);
    const a = placed.get(tie.from);
    const b = placed.get(tie.to);
    if (!one || !other || !a || !b) continue;

    // "Связи выглядят как прямые с углом линии, чтобы визуально это напоминало некий каталог из
    // карточек." An elbow rather than a curve: a catalogue is read as a tree, and a tree is drawn
    // with right angles. Out of the right of one, along, down, and into the left of the other.
    const rightward = a.x <= b.x;
    const from = { x: a.x + (rightward ? one.offsetWidth : 0), y: a.y + one.offsetHeight / 2 };
    const to = { x: b.x + (rightward ? 0 : other.offsetWidth), y: b.y + other.offsetHeight / 2 };
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
    ties.appendChild(path);

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
    ties.appendChild(label);
    drew += 1;
  }
  ties.hidden = drew === 0;
  for (const pin of surface?.querySelectorAll('.pin') || []) markHintCounts(pin);
}

/* --- what is off the screen ------------------------------------------------------------------- */
// More useful on a surface than it was on a list: a card you moved somewhere and then panned away
// from is a card that still goes into the next message.
function markOffEdge() {
  const edge = document.getElementById('off-edge');
  if (!edge || !canvas) return;
  const frame = canvas.getBoundingClientRect();
  edge.textContent = '';
  let away = 0;
  for (const pin of surface.querySelectorAll('.pin')) {
    const box = pin.getBoundingClientRect();
    if (box.right > frame.left && box.left < frame.right &&
        box.bottom > frame.top && box.top < frame.bottom) {
      continue;
    }
    const dot = document.createElement('button');
    dot.type = 'button';
    dot.className = 'edge-dot';
    dot.title = pin.querySelector('.pin-label')?.textContent || 'a card over there';
    dot.setAttribute('aria-label', `bring ${dot.title} into view`);
    dot.addEventListener('click', () => {
      const at = placed.get(cardName(pin));
      if (!at) return;
      view.x = frame.width / 2 - (at.x + CARD_WIDTH / 2) * view.scale;
      view.y = frame.height / 2 - (at.y + 40) * view.scale;
      applyView();
    });
    edge.appendChild(dot);
    away += 1;
  }
  edge.hidden = away === 0;
}

// One button, because a surface you can move things about on is a surface you can lose things on.
document.querySelector('[data-tidy]')?.addEventListener('click', tidyUp);

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
});

// The conversation folded away, and back. What folds is every card holding a block — the cards
// somebody dropped stay, because those are what the next question is about, and folding them
// would be answering a different question.
function foldConversation() {
  const cards = [...(surface?.querySelectorAll('.pin.block-card') || [])];
  if (!cards.length) return;
  const folding = !cards[0].classList.contains('put-away');
  for (const card of cards) {
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

function cardMenuFor(pin) {
  const name = pin.dataset.name;
  const joining = joiningFrom && joiningFrom !== name;
  return [
    joining
      ? { what: `join to “${labelOf(joiningFrom)}”`, act: () => finishJoin(name) }
      : { what: 'join this to another card…', act: () => startJoin(name) },
    { what: 'a line', act: () => setView(pin, 'hint') },
    { what: 'what it is', act: () => setView(pin, 'metadata') },
    { what: 'everything', act: () => setView(pin, 'full') },
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
  pin({ kind: 'folder', id: said.trim(), label: said.trim().split('/').filter(Boolean).pop() || said });
}

function clearBench() {
  // Everything comes off, including the rings. What was asked is still in the store and comes
  // back with the thread — this clears the surface, not the conversation.
  for (const node of surface?.querySelectorAll('.pin, .ring') || []) node.remove();
  placed = new Map();
  ownTies.length = 0;
  wentWith.clear();
  letGoOfAttached();
  rememberLayout();
  syncTargets();
  drawTies();
  emptyOrNot();
}

function tidyUp() {
  placed = new Map();
  // Down one column, then the next: with collision avoidance doing the vertical spacing, a column
  // of tall cards and a column of short ones both come out right.
  [...surface.querySelectorAll('.pin')].forEach((pin, index) => {
    place(pin, { x: 20 + (index % 3) * (CARD_WIDTH + GAP * 2), y: 20 });
  });
  view.x = 0;
  view.y = 0;
  applyView();
  drawTies();
  drawRings();
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
  for (const node of surface.querySelectorAll('.pin.block-card')) {
    if (!wanted.has(node.dataset.name)) {
      placed.delete(node.dataset.name);
      node.remove();
    }
  }

  for (const article of mine) {
    const id = article.dataset.block;
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
    const body = node.querySelector('.pin-body');
    const shown = body.firstElementChild;
    if (!shown || shown.dataset.rev !== article.outerHTML.length.toString()) {
      const copy = article.cloneNode(true);
      copy.hidden = false;
      copy.dataset.rev = article.outerHTML.length.toString();
      body.replaceChildren(copy);
      if (window.htmx) htmx.process(body);
      settleOverlaps();
    }
    const said = article.querySelector('.block-input, .said, h3, p');
    node.querySelector('.pin-label').textContent =
      (said?.textContent || 'a question').trim().slice(0, 60);
    node.classList.toggle('settled', article.hasAttribute('data-settled'));
    showRole(node);
    // A block's hint is what came back, not the question again — the question is already its title.
    writeHint(node);

    // Every idea this block recorded is a card of its own, joined to it. "Если я пишу идею — на
    // верстаке появляется её карточка, и далее карточки под-идей."
    for (const line of node.querySelectorAll('[data-kind="idea"][data-id]')) {
      const name = `idea:${line.dataset.id}`;
      if (!surface.querySelector(`.pin[data-name="${CSS.escape(name)}"]`)) {
        pin({ kind: 'idea', id: line.dataset.id, label: line.dataset.label }, { under: id });
      }
    }
  }
  emptyOrNot();
  loadTies();
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
  // The controls on the head do their own thing; the head itself is the switch.
  if (event.target.closest('button, a, textarea, input, select')) return;
  if (!event.target.closest('.pin-head')) return;
  holder.classList.toggle('spent');
  syncTargets();
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
    <input type="text" class="palette-field" placeholder="a project, a session, an idea, something stuck…"
           autocomplete="off" spellcheck="false" aria-label="find anything on this board">
    <ul class="palette-list"></ul>
    <p class="palette-foot">Enter puts it on the workbench · Esc closes</p>
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
function paletteMatches(said) {
  const words = said.toLowerCase().split(/\s+/).filter(Boolean);
  return everythingOnThePage()
    .filter((one) => words.every((word) => `${one.kind} ${one.name}`.toLowerCase().includes(word)))
    .slice(0, 12);
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
  pin({ kind: one.kind === 'checkout' ? 'instance' : one.kind, id: one.id, label: one.name });
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
});

function activeCards() {
  // Not a copy of an earlier question, and not something already inside a ring: those are the
  // record, and a record that took part in the next question would grow by reading itself.
  return [...pins.querySelectorAll('.pin:not(.spent):not(.ringed)[data-kind]')];
}

// Where a snapshot goes: clear of everything already on the bench, so it does not land on top of
// the cards it is a copy of.
function belowEverything() {
  const all = [...placed.values()];
  if (!all.length) return { x: 20, y: 20 };
  return { x: 20, y: Math.max(...all.map((at) => at.y)) + 260 };
}

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
    // Along a row, which is what a group of four folded cards wants to be.
    place(copy, { x: at.x + index * (CARD_WIDTH + GAP), y: at.y }, { avoid: false });
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
showActiveThread();

/* --- and the first paint ----------------------------------------------------------------------- */
// Everything above defines how the surface behaves; this is what puts the conversation on it when
// the page opens, rather than only when the next event arrives.
syncBlocks();
emptyOrNot();
