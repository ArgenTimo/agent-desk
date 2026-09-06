/*
  Three things, and the third one is the one worth reading.

  1. The estimator: arithmetic in the browser, so nothing anybody types on this page leaves it.
  2. The two small interactions the page needs.
  3. Analytics that do not exist until somebody agrees to them.

  On the third: both Google Analytics and Yandex Metrica are wired here, and neither is *requested*
  before consent. That distinction matters — a page that loads gtag.js and then decides whether to
  send events has already told Google that this browser visited this page. So there is no script
  tag in the markup for either of them, and the tag is injected only after a yes.
*/

(() => {
  'use strict';

  // --- what it costs -------------------------------------------------------------------------
  //
  // Deliberately simple and deliberately honest about being an estimate. The shape is the thing
  // that has to be right: more value costs more, more excess costs less, and travel is not priced
  // like a house. Nobody should be able to read a real premium out of it, and the page says so in
  // the same block as the number.
  const BASE = { car: 22, home: 11, travel: 8 };
  // Calibrated so each one lands in the range that kind of policy actually costs — a car in the
  // tens per month, a home in the twenties, a trip in the tens for the trip. A page whose numbers
  // do not hang together is worse than a page with no numbers, because the one thing a visitor
  // came to check is the one thing it got wrong.
  const PER_THOUSAND = { car: 1.6, home: 0.05, travel: 2.4 };
  // What a higher excess is worth. A multiplier rather than a subtraction, so it cannot take an
  // estimate below zero on a cheap policy.
  const EXCESS_FACTOR = { 100: 1.2, 250: 1.12, 350: 1.06, 500: 1, 1000: 0.86 };

  // What "worth" and the excess mean depends on what is being insured, and offering a £250 excess
  // on a trip or pricing a house like a car is the kind of detail that makes a whole page look
  // careless. The options here match the "excess from" line on each card below.
  const SHAPE = {
    car: { unit: 'a month, indicative', worth: 'What is the car worth?',
           why: 'The most we would ever pay out, which is the biggest thing in the price.',
           excesses: [250, 500, 1000], value: 12000, step: 500 },
    home: { unit: 'a month, indicative', worth: 'What would it cost to rebuild and refurnish?',
            why: 'Not what the house would sell for — what it would cost to put back.',
            excesses: [350, 500, 1000], value: 250000, step: 5000 },
    travel: { unit: 'for the trip, indicative', worth: 'What did the trip cost?',
              why: 'What you would be out of pocket if it were cancelled.',
              excesses: [100, 250, 500], value: 3000, step: 250 },
  };

  const kind = document.getElementById('kind');
  const value = document.getElementById('value');
  const excess = document.getElementById('excess');
  const figure = document.getElementById('figure');
  const note = document.getElementById('note');

  const money = new Intl.NumberFormat(undefined, {
    style: 'currency',
    currency: 'GBP',
    maximumFractionDigits: 0,
  });

  // The two fields that mean different things for different policies, put in step with the choice.
  function reshape() {
    const shape = SHAPE[kind.value];
    document.querySelector('label[for="value"]').textContent = shape.worth;
    const why = value.closest('.field').querySelector('.why');
    if (why) why.textContent = shape.why;
    value.step = String(shape.step);
    value.value = String(shape.value);
    document.querySelector('.estimate-unit').textContent = shape.unit;

    const chosen = Number(excess.value);
    excess.textContent = '';
    for (const amount of shape.excesses) {
      const option = document.createElement('option');
      option.value = String(amount);
      option.textContent = money.format(amount);
      option.selected = amount === chosen || (!shape.excesses.includes(chosen) && amount === shape.excesses[1]);
      excess.appendChild(option);
    }
  }

  function estimate() {
    const worth = Number(value.value);
    if (!Number.isFinite(worth) || worth <= 0) {
      figure.textContent = '£—';
      note.textContent = 'Put in roughly what it is worth and the estimate appears.';
      return;
    }
    const price =
      (BASE[kind.value] + (worth / 1000) * PER_THOUSAND[kind.value]) *
      (EXCESS_FACTOR[excess.value] || 1);
    figure.textContent = money.format(Math.max(5, Math.round(price)));
    note.textContent =
      'Worked out in your browser from three answers. A real quote uses more than three, so this ' +
      'will move — it is not an offer.';
  }

  kind.addEventListener('change', () => {
    reshape();
    estimate();
  });
  for (const field of [value, excess]) {
    field.addEventListener('input', estimate);
    field.addEventListener('change', estimate);
  }
  reshape();
  estimate();

  document.getElementById('continue').addEventListener('click', () => {
    // Nothing is submitted from this page: wiring it to an endpoint is a decision about where
    // personal data goes, and it belongs to whoever owns the endpoint.
    note.textContent =
      'This page does not send anything anywhere yet. Connect it to your quote service, and say ' +
      'on the next screen why each field is needed.';
    note.scrollIntoView({ block: 'nearest' });
    measure('quote_continue', { kind: kind.value, excess: excess.value });
  });

  document.querySelector('[data-open-privacy]')?.addEventListener('click', (event) => {
    event.preventDefault();
    // In the page rather than an alert: a modal dialog blocks everything and is the wrong shape
    // for a note to whoever is building this.
    const said = document.createElement('p');
    said.className = 'fineprint';
    said.textContent =
      'Write the privacy notice before this ships. It has to say what is collected, who else ' +
      'sees it, how long it is kept, and how to have it deleted.';
    event.target.replaceWith(said);
  });

  // --- analytics, and the consent that comes first ---------------------------------------------
  const CHOICE = 'northwind:measuring';
  const GA_ID = 'G-XXXXXXXXXX';
  // The counter id, as a number. Zero means "not configured", and nothing is requested from
  // Yandex while it is zero — a placeholder that made a request to prove it was a placeholder
  // would be exactly the thing the consent banner promises does not happen.
  const METRICA_ID = 0;

  const banner = document.getElementById('consent');
  let loaded = false;

  function remembered() {
    try {
      return localStorage.getItem(CHOICE);
    } catch {
      // A browser that will not remember the choice asks again, which is the safe direction.
      return null;
    }
  }

  function remember(answer) {
    try {
      localStorage.setItem(CHOICE, answer);
    } catch {
      // Nothing to do about it, and nothing that should stop the page working.
    }
  }

  function loadGoogle() {
    if (GA_ID.includes('X')) return; // not configured; do not make a request to prove it
    const tag = document.createElement('script');
    tag.async = true;
    tag.src = `https://www.googletagmanager.com/gtag/js?id=${GA_ID}`;
    document.head.appendChild(tag);
    window.dataLayer = window.dataLayer || [];
    window.gtag = function gtag() {
      window.dataLayer.push(arguments);
    };
    window.gtag('js', new Date());
    // No advertising features and no cross-site identifiers: this is a brochure site counting
    // page views, and asking for more than that is what makes a consent banner a lie.
    window.gtag('config', GA_ID, { anonymize_ip: true, allow_google_signals: false });
  }

  function loadMetrica() {
    if (!METRICA_ID) return;
    (function (m, e, t, r, i, k, a) {
      m[i] =
        m[i] ||
        function () {
          (m[i].a = m[i].a || []).push(arguments);
        };
      m[i].l = 1 * new Date();
      k = e.createElement(t);
      a = e.getElementsByTagName(t)[0];
      k.async = 1;
      k.src = r;
      a.parentNode.insertBefore(k, a);
    })(window, document, 'script', 'https://mc.yandex.ru/metrika/tag.js', 'ym');

    // `webvisor` is off on purpose. A quote form carries dates of birth and registrations, and
    // recording that session puts personal data somewhere nobody agreed to put it.
    window.ym(METRICA_ID, 'init', {
      clickmap: true,
      trackLinks: true,
      accurateTrackBounce: true,
      webvisor: false,
      trackHash: true,
    });
  }

  function startMeasuring() {
    if (loaded) return;
    loaded = true;
    loadGoogle();
    loadMetrica();
  }

  // Every call site can use this whether or not anybody agreed: with no consent it does nothing,
  // which means no part of the page has to know what was decided.
  function measure(event, detail) {
    if (!loaded) return;
    window.gtag?.('event', event, detail);
    window.ym?.(METRICA_ID, 'reachGoal', event, detail);
  }

  function ask() {
    banner.hidden = false;
  }

  function answer(said) {
    remember(said);
    banner.hidden = true;
    if (said === 'yes') startMeasuring();
  }

  for (const button of banner.querySelectorAll('[data-consent]')) {
    button.addEventListener('click', () => answer(button.dataset.consent));
  }

  document.getElementById('change-consent').addEventListener('click', () => {
    // Consent you cannot withdraw is not consent. Turning it off stops anything further being
    // sent; what has already gone is gone, and saying so honestly is better than implying a
    // reload undoes it.
    remember('');
    banner.hidden = false;
    if (loaded) {
      window.location.reload();
    }
  });

  const already = remembered();
  if (already === 'yes') {
    startMeasuring();
  } else if (already !== 'no') {
    ask();
  }
})();
