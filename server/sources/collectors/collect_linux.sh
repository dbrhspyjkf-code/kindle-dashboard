#!/bin/sh
# Linux 指标采集 —— 输出统一 JSON。本机直读/推agent 两处复用。
# 字段契约见 docs/data-contract.md(device 段 raw):
#   cpu_pct, mem_used, mem_total, net_rx, net_tx, disk_read, disk_write(均 bytes/s), disks[]
# 自动探测:网卡(累加非 lo)、磁盘 IO(累加整盘)、分区(df 真实挂载)。无硬编码设备名。
SLEEP="${COLLECT_INTERVAL:-1}"

read_cpu() {  # 输出: total idle (用 %.0f 防 mawk 大数科学计数/截断)
  awk '/^cpu /{printf "%.0f %.0f\n", $2+$3+$4+$5+$6+$7+$8+$9, $5+$6}' /proc/stat
}
read_net() {  # 输出: rx tx (累加非 lo 接口)
  awk 'NR>2{gsub(/:/," "); if($1!="lo"){rx+=$2; tx+=$10}} END{printf "%.0f %.0f\n", rx, tx}' /proc/net/dev
}
read_disk() { # 输出: read_bytes write_bytes (累加整盘)
  r=0; w=0
  for d in /sys/block/*; do
    [ -e "$d/stat" ] || continue
    name=$(basename "$d")
    case "$name" in loop*|ram*|dm-*|zram*|sr*) continue;; esac
    set -- $(cat "$d/stat")
    r=$((r + $3 * 512)); w=$((w + $7 * 512))
  done
  echo "$r $w"
}
read_mem() {  # 输出: used total (bytes)
  awk '/^MemTotal:/{t=$2} /^MemAvailable:/{a=$2} END{printf "%.0f %.0f\n", (t-a)*1024, t*1024}' /proc/meminfo
}

set -- $(read_cpu);  c1t=$1; c1i=$2
set -- $(read_net);  rx1=$1; tx1=$2
set -- $(read_disk); dr1=$1; dw1=$2
sleep "$SLEEP"
set -- $(read_cpu);  c2t=$1; c2i=$2
set -- $(read_net);  rx2=$1; tx2=$2
set -- $(read_disk); dr2=$1; dw2=$2

dt=$((c2t - c1t)); di=$((c2i - c1i))
cpu=0; [ "$dt" -gt 0 ] && cpu=$(( (100 * (dt - di)) / dt ))
nrx=$(( (rx2 - rx1) / SLEEP )); [ "$nrx" -lt 0 ] && nrx=0
ntx=$(( (tx2 - tx1) / SLEEP )); [ "$ntx" -lt 0 ] && ntx=0
drd=$(( (dr2 - dr1) / SLEEP )); [ "$drd" -lt 0 ] && drd=0
dwr=$(( (dw2 - dw1) / SLEEP )); [ "$dwr" -lt 0 ] && dwr=0
set -- $(read_mem); mu=$1; mt=$2

# 分区(真实挂载,排除虚拟 fs)
disks=$(df -kP -x tmpfs -x devtmpfs -x overlay -x squashfs -x efivarfs 2>/dev/null | awk '
  NR>1 && $2+0>0 {
    used=$3*1024; total=$2*1024; pct=$5; gsub(/%/,"",pct);
    if (n++) printf ",";
    printf "{\"name\":\"%s\",\"used\":%.0f,\"total\":%.0f,\"pct\":%d}", $6, used, total, pct
  }')

printf '{"cpu_pct":%d,"mem_used":%d,"mem_total":%d,"net_rx":%d,"net_tx":%d,"disk_read":%d,"disk_write":%d,"disks":[%s]}\n' \
  "$cpu" "$mu" "$mt" "$nrx" "$ntx" "$drd" "$dwr" "$disks"
