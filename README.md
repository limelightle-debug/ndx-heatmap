# Nasdaq 100（iPhone用ウェブアプリ）

ナスダック100の騰落率、指数への寄与、セクター、ウェイト、時価総額上位20社の順位推移を表示するアプリです。
GitHub Pages で公開し、GitHub Actions が米国市場の取引時間中に約15分ごとにデータを更新します。
iPhone では Safari の「ホーム画面に追加」で、アプリとして使えます。

## 中身

| ファイル | 役割 |
|---|---|
| `index.html` | アプリ本体 |
| `manifest.webmanifest` / `sw.js` / `icons/` | ホーム画面アプリ化とオフライン表示 |
| `d3.min.js` | ヒートマップの描画ライブラリ |
| `data/ndx.json` | 表示するデータ（自動で更新されます） |
| `data/rank_history.json` | 時価総額順位の月次履歴（2016年10月〜。今月分は自動で更新されます） |
| `scripts/update_ndx.py` | finviz からデータを取得するスクリプト |
| `.github/workflows/update-data.yml` | 15分ごとの自動実行の設定 |

## 公開の手順（初回だけ、約10分）

### 1. リポジトリを作る
1. GitHub にログインします（アカウントがなければ作成）。
2. 右上の「+」→「New repository」。
3. Repository name に `ndx-heatmap` と入力し、**Public** を選んで「Create repository」。
   （無料プランの GitHub Pages は Public リポジトリが必要です。中身にパスワードなどの秘密情報はありません）

### 2. ファイルを入れる
1. 作ったリポジトリの画面で「uploading an existing file」をクリックします。
2. このフォルダの中身を**すべて**ドラッグして入れ、「Commit changes」。
   - Mac では `.github` フォルダが隠れています。Finder で `Command + Shift + .`（ピリオド）を押すと表示されるので、一緒にドラッグしてください。
   - うまく入らない場合は、「Add file」→「Create new file」で、ファイル名に `.github/workflows/update-data.yml` と入力し、同じファイルの中身を貼り付けて保存します。

### 3. GitHub Pages を有効にする
1. リポジトリの「Settings」→ 左メニューの「Pages」。
2. 「Build and deployment」の Source を「Deploy from a branch」、Branch を `main` / `(root)` にして「Save」。
3. 1〜2分後、`https://<あなたのユーザー名>.github.io/ndx-heatmap/` でアプリが開けるようになります。

### 4. 自動更新を動かす
1. リポジトリの「Actions」タブを開きます。確認画面が出たら有効化のボタンを押します。
2. 左の「Update NDX data」→ 右の「Run workflow」で一度手動実行します。
3. 緑のチェックが付けば成功です。市場が閉まっている時間は「no change」で終わるのが正常です。
4. 以後は、米国市場の取引時間中（日本時間で夏時間は22:30〜翌5:00、冬時間は23:30〜翌6:00）に約15分ごとに自動で更新されます。

### 5. iPhone のホーム画面に追加
1. iPhone の Safari で `https://<あなたのユーザー名>.github.io/ndx-heatmap/` を開きます。
2. 下の共有ボタン → 「ホーム画面に追加」。
3. ホーム画面の「Nasdaq 100」アイコンから、アプリとして起動できます。

## 知っておくこと
- GitHub の定期実行は混雑時に数分〜十数分遅れることがあります。
- アプリは開いたとき、画面に戻ったとき、5分ごとに最新データを読み込みます。右上の ↻ で手動更新もできます。
- 取引時間中に45分以上更新がないと、画面上部に「更新が遅れています」と表示されます。
- 60日間リポジトリに動きがないと GitHub が定期実行を止めることがありますが、取引日には毎回データが書き込まれるので通常は止まりません。
- 騰落率・時価総額は finviz、指数ウェイトは Invesco QQQ の保有比率（1日1回更新）から取得しています。
- 順位推移の過去分は companiesmarketcap.com の月末時価総額から作成し、今月分は finviz の時価総額で毎回上書きします。月が替わると前月の値がそのまま月末の値として残ります。
- データの取得先は finviz と Invesco です。finviz 側の仕様変更で取得できなくなった場合は、Actions の実行結果が赤くなります。
