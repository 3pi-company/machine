#!/usr/bin/env bash
# حلقة المزامنة: دورة كل INTERVAL ثانية (الافتراضي 600 = 10 دقايق) لمدة حوالي 5 ساعات ونص، وقبل ما تخلص بحوالي 15 دقيقة
# بتطلق الحلقة اللي بعدها (concurrency بتخليها تستنى لحد ما دي تخلص، فمفيش فجوة ولا تداخل). مهلة أمان لكل دورة.
# بدل الـcron اللي GitHub بيتأخر فيه عندنا (18 تشغيلة من 96 في اليوم). المراقب watchdog.yml بيعيد التشغيل لو الحلقة وقفت.
set -u
INTERVAL="${INTERVAL:-600}"; LIFE=$(( ${LIFE_MIN:-335} * 60 )); NEXT_AT=$(( ${NEXT_MIN:-320} * 60 ))
START=$(date +%s); SENT=0
next() { gh api -X POST "repos/$GITHUB_REPOSITORY/actions/workflows/sync.yml/dispatches" -f ref=main >/dev/null 2>&1 && SENT=1; }
while [ $(( $(date +%s) - START )) -lt "$LIFE" ]; do
  S=$(date +%s)
  timeout 600 bash code/tools/iterate.sh || echo "iteration: timeout-or-fail"
  E=$(date +%s)
  [ "$SENT" -eq 0 ] && [ $(( E - START )) -ge "$NEXT_AT" ] && next
  W=$(( INTERVAL - (E - S) )); [ "$W" -gt 0 ] && sleep "$W"
done
[ "$SENT" -eq 0 ] && next
exit 0
