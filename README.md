# ReactCollect 補貨監控（本機網頁版）

追蹤 ReactCollect 商品頁的庫存狀態，缺貨 → 有貨立刻在頁面上跳通知。

## 怎麼跑

1. 安裝 Python 3（https://www.python.org/downloads/，安裝時勾選 Add to PATH）
2. Windows 雙擊 `run.bat`；Mac / Linux 在終端機跑 `bash run.sh`
3. 瀏覽器會自動打開 http://localhost:8787

> 純 Python 標準函式庫，不需 pip 安裝任何套件。

## 怎麼用

- 在輸入框貼上 `reactcollect.com/products/...` 的商品頁連結 → 加入追蹤
- 每個商品可以 ⏸ 暫停 / ▶ 恢復追蹤、🔄 單獨重查、🗑 移除
- 後台每 15 分鐘自動檢查一次追蹤中的商品
- 「缺貨 → 有貨」會記進事件紀錄，開著頁面時會跳瀏覽器通知＋🚨 標記
- 追蹤清單存在本機 `data.json`，刪掉即清空

## 注意

- 目前只支援 reactcollect.com 的商品連結
- 只監控、不自動下單，看到補貨請手動去買
- 檢查太頻繁可能被網站暫時擋掉，預設 15 分鐘一輪請勿自行調太高
