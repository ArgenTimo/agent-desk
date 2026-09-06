# An insurance site, on this branch and not on main

Built from the idea *«создать сайт на основе лучших практик страхования и обвесить google и
яндекс аналитикой»*, on `experiment/insurance-site` because it is asked for and because it is not
what this repository is.

**This must not merge to main.** agent-desk is a read-first console over Claude Code sessions
(CLAUDE.md, §2: "the pull toward turning this into a second ai-worker is strong and must be
resisted"). A product website is a different product with a different lifecycle, and the right
home for it is a repository of its own. When there is one, this directory moves there whole — it
has no dependency on anything above it, which is deliberate.

## What it is

A static site. No build step, no framework, no server: three files and a folder of assets, opened
by double-clicking `index.html` or served by any web server. That is not a shortcut — for a
brochure site with a quote form it is the shape that stays working when nobody has touched it for
two years.

```
index.html      the page
styles.css      one stylesheet, one set of tokens
site.js         the quote estimate, the form, and consent-gated analytics
```

## The placeholders, and why they are placeholders

Every one of these is deliberately not filled in, and a site that shipped with them invented would
be a site that lies about a regulated business:

| Placeholder | What goes there |
|---|---|
| `Northwind Insurance` | the actual trading name |
| `LICENCE-PLACEHOLDER` | the real licence or registration number, from the regulator |
| `COMPANY-PLACEHOLDER` | the registered company number and address |
| `G-XXXXXXXXXX` | the GA4 measurement id |
| `00000000` | the Yandex Metrica counter id |
| the two phone numbers and the email | the real ones |

There are **no testimonials, no ratings, no customer counts and no awards** anywhere in the
markup. Those are the things a template most wants to invent and the things a visitor is most
entitled to rely on; write them when they are true, with the source next to them.

## The insurance practices it is built around

Not a style exercise — each of these is a thing that makes an insurance page work or fail.

1. **Price is the question, so it is the first interaction.** The quote estimator is above the
   fold and gives a number without asking who you are. A form that demands a name and a phone
   number before saying anything is why people leave.
2. **The estimate says it is an estimate**, every time, in the same place as the number. An
   indicative figure presented as a price is the complaint that follows the sale.
3. **What is *not* covered sits beside what is**, at the same size. Exclusions in smaller type
   below the fold is the pattern regulators write rules about, and it is also just dishonest.
4. **The excess is on the card**, not in a document. It is the number that decides whether a
   policy is any use, and hiding it makes the cheap column look better than it is.
5. **How to claim is a top-level section.** People choose an insurer for the day something goes
   wrong; a site that only sells is a site that answers the easy question.
6. **Every form field says why it is needed.** A date of birth on an insurance form is not
   obvious; saying "it sets your premium band" costs one line and stops the abandonment.
7. **The renewal and cancellation terms are stated**, because the cooling-off period and the
   auto-renewal are the two things people are surprised by later.

## Analytics, and the consent that has to come first

GA4 and Yandex Metrica are both wired, and **neither loads until somebody agrees**. That is the
practice and in several jurisdictions the law: analytics is not strictly necessary for a brochure
site to work, so it needs consent, and the banner therefore has a real "no" that is as easy to
press as the "yes".

- Nothing is requested from either vendor before the choice is made — no script tag, no pixel.
- The choice is remembered in `localStorage` and can be changed from the footer at any time,
  because consent you cannot withdraw is not consent.
- Metrica is initialised with `trackHash` and without session recording: a form on an insurance
  site carries dates of birth and vehicle registrations, and recording that session would put
  personal data somewhere nobody agreed to put it.
- The quote form does not submit anywhere. Wiring it to a real endpoint is a decision about where
  personal data goes, and it belongs to whoever owns that endpoint.
