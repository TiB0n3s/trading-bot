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

Official/regulator/exchange sources should be preferred when a concept appears
in both an official source and a consumer education source.

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

## Guardrails

- Follow links only within approved seed domains.
- Store source URL, retrieved timestamp, content hash, and corpus version.
- Do not ingest copyrighted books or podcasts beyond metadata/operator notes.
- Do not treat education content as market-moving news.
- Do not treat education content as live authority.
- Any future education-corpus ingestion job should report source counts through
  `python3 ops_check.py trading-education-health`.
