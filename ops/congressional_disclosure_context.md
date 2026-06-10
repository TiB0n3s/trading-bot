# Congressional Trade Disclosure Context

Congressional trading disclosures may be used as event context, not as a copy-trading signal.

## Approved Source Roles

Official source-of-truth:

- House Clerk Financial Disclosure Reports
- Senate Public Financial Disclosure

Screening and aggregation:

- Quiver Quantitative
- Apify congressional stock-trade trackers
- CryptoDaily government-trading and crypto-policy coverage

Aggregators are useful for discovery, but any market-moving inference should require an official House/Senate filing or independent reputable reporting before being treated as confirmed context.

CryptoDaily is classified as a trusted `deep_analysis` reference for
government-trading coverage and crypto-policy spillover context. It is not an
`official` disclosure source; official House/Senate filings remain the source of
truth for transaction date, filing date, owner relationship, ticker, amount
range, and chamber/member attribution.

## Runtime Interpretation

The event pipeline represents these rows as:

- `event_type=congressional_trade_disclosure`
- `intent_category=public_official_trade_disclosure`
- `intent_scope=public_official_disclosure`
- `authority=context_only_no_standalone_buy_authority`

These events are intentionally neutral/watch-only by default. They can add context for review, but they do not approve trades, block trades, or increase size by themselves.

## Required Limitations

Every congressional disclosure event should carry these limitations:

- delayed STOCK Act reporting
- broad dollar range, not exact size
- possible spouse/dependent transaction
- no proof the trade was informed, timely, or personally directed by the official

## Recommended Review Fields

When entering or reviewing one of these events, capture:

- ticker
- official name and chamber
- transaction type
- transaction date
- filing date
- disclosure lag days
- dollar range
- owner relationship, if available
- committee relevance, if material
- official filing URL
- aggregator URL, if used for screening
