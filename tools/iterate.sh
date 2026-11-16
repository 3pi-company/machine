#!/usr/bin/env bash
# دورة مزامنة واحدة لـC-0002 وC-0001 (قراءة فقط من جوليب). التفاصيل في ملف داخلي بس، والسجل العام بيطبع سطر واحد لكل عميل
# (مشغّل صامت: ممنوع أرقام أو أسماء أو باركودات في سجل ريبو عام). فشل عميل ما بيوقفش التاني.
set -u
ROOT="$(pwd)"; CODE="$ROOT/code"; LOG="$ROOT/iter.log"; : > "$LOG"
GN="3pi"; GE="353338283+3pi-company@users.noreply.github.com"
R2="https://x-access-token:${PUSH_TOKEN}@github.com/3pi-company/c0002-dashboard.git"
R1="https://x-access-token:${PUSH_TOKEN}@github.com/3pi-company/c0001-dashboard.git"
cp_if() { [ -f "$1" ] && cp "$1" "$2"; }
verdict() { grep -o '"result": *"[a-z_]*"' "$1" 2>/dev/null | head -1 | sed 's/.*: *//' || true; }

push_data() {  # $1 مجلد الفرع، $2 الـremote
  ( cd "$1" && git config user.name "$GN" && git config user.email "$GE" && git add data
    if ! git diff --cached --quiet; then
      git commit -q -m "machine sync $(date -u +%H%M)"
      git push -q "$2" HEAD:data || { git pull -q --rebase "$2" data && git push -q "$2" HEAD:data; }
    fi ) >>"$LOG" 2>&1
}

c0002() {
  rm -rf "$ROOT/db2" "$ROOT/w2"; mkdir -p "$ROOT/w2/data/rest_store" "$ROOT/w2/data/master"
  git clone -q --depth 1 --branch data "$R2" "$ROOT/db2" >>"$LOG" 2>&1 || { echo "c0002: clone-fail"; return 1; }
  cp_if db2/data/rest_store/pos_store.json w2/data/rest_store/; cp_if db2/data/master/master_c0002.json w2/data/master/
  cp_if db2/data/health/sync.json w2/prev_health.json
  ( cd w2 && timeout 120 python ../code/c0002/sync.py ) >>"$LOG" 2>&1 || true
  ( cd w2 && timeout 120 python ../code/c0002/stock_pull.py ) >>"$LOG" 2>&1 || true
  mkdir -p db2/data/health db2/data/rest_store db2/data/store
  cp_if w2/out/data/rest_store/pos_store.json db2/data/rest_store/
  cp_if w2/out/data/health/sync.json db2/data/health/; cp_if w2/out/data/health/stock.json db2/data/health/
  [ -d w2/out/data/store ] && cp -r w2/out/data/store/. db2/data/store/
  push_data "$ROOT/db2" "$R2"
  echo "c0002: $(verdict w2/out/data/health/sync.json)"
}

c0001() {
  rm -rf "$ROOT/db1" "$CODE/c0001/out"; mkdir -p "$CODE/c0001/data/master"
  git clone -q --depth 1 --branch data "$R1" "$ROOT/db1" >>"$LOG" 2>&1 || { echo "c0001: clone-fail"; return 1; }
  cp_if db1/data/master/master_c0001.json "$CODE/c0001/data/master/"
  mkdir -p "$CODE/c0001/data/store"; cp_if db1/data/store/stock.json "$CODE/c0001/data/store/"   # عشان تنبيه الهامش يتقصر على الأصناف المباعة أو اللي في رصيد الفرع (relevant_pids)
  ( cd "$CODE/c0001" && BACKFILL_DAYS=60 timeout 120 python pull_sales.py ) >>"$LOG" 2>&1 || true
  ( cd "$CODE/c0001" && timeout 120 python stock_pull.py ) >>"$LOG" 2>&1 || true
  O="$CODE/c0001/out/data"; mkdir -p db1/data/health db1/data/rest_store db1/data/store
  cp_if "$O/rest_store/pos_store.json" db1/data/rest_store/
  cp_if "$O/health/sync.json" db1/data/health/; cp_if "$O/health/stock.json" db1/data/health/
  [ -d "$O/store" ] && cp -r "$O/store/." db1/data/store/
  push_data "$ROOT/db1" "$R1"
  echo "c0001: $(verdict "$O/health/sync.json")"
}

c0002 || true
c0001 || true
