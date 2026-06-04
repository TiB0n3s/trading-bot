# Trading Education Source Contract

Version: `trading_education_corpus_v1`

This contract defines sources the bot may use for education context. It does
not grant live trading authority. Education material can explain concepts,
risks, and terminology, but it cannot approve, block, size, or execute trades.

## Approved Seed Sources

These may be ingested from their seed URL and same-domain links only:

- SEC Investor.gov / Investor Education
- FINRA Investing Basics
- CFTC Futures Market Basics
- CME Group Education
- NerdWallet Investing Education
- Investopedia
- Charles Schwab Learn Trading

Official/regulator/exchange sources should be preferred when a concept appears
in both an official source and a consumer education source.

Schwab trading article cards currently tracked as approved child seeds:

- `https://www.schwab.com/learn/story/what-are-derivatives`
- `https://www.schwab.com/learn/story/options-strategy-covered-call`
- `https://www.schwab.com/learn/story/options-expiration-definitions-checklist-more`
- `https://www.schwab.com/learn/story/how-to-use-weekly-stock-options`
- `https://www.schwab.com/learn/story/what-happens-to-options-when-stock-splits`
- `https://www.schwab.com/learn/story/why-stocks-sometimes-ignore-good-or-bad-news`
- `https://www.schwab.com/learn/story/ins-and-outs-short-selling`
- `https://www.schwab.com/learn/story/ways-traders-spot-rallys-potential-end`
- `https://www.schwab.com/learn/story/aligning-your-options-with-implied-volatility`
- `https://www.schwab.com/learn/story/heikin-ashi-candles-reversals-and-strategies`
- `https://www.schwab.com/learn/story/pre-ipo-company-equity-6-actions-to-take-now`

If Schwab returns an authorization/error page to the VM, the ingestion job
records `fetch_failed` instead of storing the error page as education content.
If an operator manually exports the article HTML/text from a browser, load it
through the same schema with:

```bash
python3 ops_check.py trading-education-ingest \
  --manual-file /path/to/schwab_article.html \
  --url https://www.schwab.com/learn/story/what-are-derivatives \
  --title "What Are Derivatives? A Guide to Financial Contracts"
python3 ops_check.py trading-education-review
```

Manual snapshots are marked with `ingestion_method=manual_snapshot` and may be
stored as `needs_review` if the content is short, has no concept match, or has
low extraction confidence.

## Reference-Only Sources

These may be referenced by metadata or operator notes only. Do not ingest full
copyrighted text or unrestricted podcast/book content:

- `The Intelligent Investor` by Benjamin Graham
- `Unshakable` by Tony Robbins
- Ric Edelman books and podcast

## Manual Review Only

These are context/hypothesis sources, not crawl targets:

- Mobile investment apps and broker education
- Trendsetter / consumer observation heuristic

## Outside Bot Scope

Financial advisor guidance is relevant to personal financial planning, but it is
not an automated trading-intelligence source.

## Curated Concept Pack

The corpus also includes source-neutral summaries for core trading concepts.
These are used to label and explain bot behavior; they do not grant authority.

- Strategy versus style
- Trend trading
- Range trading
- Breakout trading
- Reversal trading
- Gap trading
- Pairs trading
- Arbitrage
- Momentum trading
- Practice and risk validation before live use
- Backtesting and overfitting control
- News, expectations, and positioning
- Short selling risk
- Rally exhaustion and exit patterns
- Implied volatility context
- Heikin Ashi trend reversal context
- IPO liquidity and insider restriction context

The concept pack should be used for reporting, education context, feature
taxonomy, and future AI explanation prompts. It must not become a live approval,
blocking, sizing, or execution path without separate promotion governance.

## Ingestion Command

Run a bounded seed refresh with:

```bash
python3 ops_check.py trading-education-ingest --max-pages 6 --no-follow
python3 ops_check.py trading-education-health
```

The ingestion job stores compact metadata in `trading_education_pages`:

- source key/name/tier
- URL and retrieved timestamp
- content hash
- compact summary
- matched concept keys
- related feature names
- corpus/source policy version
- runtime effect
- fetch status/error

It does not store full copyrighted books or unrestricted long-form content.
Fetch failures are retained for observability because public websites may block
automated requests.

## Guardrails

- Follow links only within approved seed domains.
- Store source URL, retrieved timestamp, content hash, and corpus version.
- Do not ingest copyrighted books or podcasts beyond metadata/operator notes.
- Do not treat education content as market-moving news.
- Do not treat education content as live authority.
- Backtesting concepts should support promotion readiness, walk-forward
  validation, out-of-sample review, and overfitting-risk reporting. They should
  not justify live authority from in-sample results alone.
- Keep pasted/reference material normalized as concise concept metadata instead
  of storing long copyrighted or vendor-authored passages.
- Any future education-corpus ingestion job should report source counts through
  `python3 ops_check.py trading-education-health`.
