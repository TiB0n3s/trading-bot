# Operations Notes

This directory stores operational reference files for the trading bot.

## Cron

`crontab.tradingbot.current.txt` is a version-controlled snapshot of the
production `tradingbot` user's current crontab.

It is not automatically installed by the repo.

To compare the live server schedule against the tracked copy:

```bash
cd ~/trading-bot
crontab -l > /tmp/live-crontab.txt
diff -u ops/crontab.tradingbot.current.txt /tmp/live-crontab.txt

To restore intentionally after review:

crontab ops/crontab.tradingbot.current.txt

Do not restore blindly. Review paths, environment loading, market schedule,
and any newly added jobs first.
