"""説明の1文に、社名・人名らしい言葉が入っていないかを見る（誤って止めることが少ない印だけ）。

印が付かない固有名詞（「田中の週報」「カタカナの社名だけ」など）は機械では見つけきれない。
その分は、送るスキル（sho-san-share）の下見で説明の一覧を本人に全部見せて補う。
同じ決まりを sho-san-share の sharelib/propernoun.py にも置く（見本: tests/fixtures/proper_noun_cases.json）。

- 会社の印（どこにあっても止める）: 株式会社・有限会社・合同会社・(株)・(有)・御中（㈱・㈲は NFKC で (株)・(有) になる）
- 会社の印（前に固有の語が付いたときだけ止める）: 工務店・ホーム・ハウス・建設・不動産・事務所・商事・商店。
  前に付いた漢字・カタカナの並びが一般の言い方（マイホーム・モデルハウス・住宅建設・設計事務所など）なら通す。
  後ろが「ページ」「メーカー」「業」「会社」などの一般の言い方なら通す
- 人の印: 漢字・カタカナの並び＋さん・様・氏・くん・ちゃん・部長・課長・社長・店長。
  前が一般の言い方（お客様・担当者様・皆様・営業部長など）なら通す。前に何も無い（社長向け）なら通す
- 場所の印（〇〇展示場・〇〇支店）は、一般の言い方と見分けにくく誤って止めることが多いので見ない
- カタカナの連続は一律には止めない（正当な説明が全滅するため）
"""

from __future__ import annotations

import re
import unicodedata

_HAN = "㐀-䶿一-鿿々〆ヶ"  # 漢字・々・〆・ヶ
_KATA = "ァ-ヺー"  # カタカナ・長音
_RUN_RE = re.compile("[" + _HAN + _KATA + "]+$")

STRONG_COMPANY_RE = re.compile(r"株式会社|有限会社|合同会社|\((?:株|有)\)|御中")

_COMPANY_SUFFIX_RE = re.compile(r"(工務店|ホーム|ハウス|建設|不動産|事務所|商事|商店)")
_COMPANY_GENERIC_BEFORE = {
    "マイ", "モデル", "オープン", "住宅", "注文住宅", "戸建", "戸建て", "新築", "土木", "総合", "設計", "建築",
    "会計", "法律", "税理士", "司法書士", "行政書士", "特許", "公共", "民間", "地元", "地域", "大手", "中小", "地場",
    "老人", "介護", "賃貸", "売買", "商業", "投資", "管理", "仲介", "工事", "外構", "リフォーム", "増改築",
    "グループ", "シェア", "ツリー", "ログ", "トレーラー", "ゲスト", "ビニール",
}
# 後ろに続くと一般の言い方になるもの（ホームページ・ハウスメーカー・建設業・建設現場など）
_COMPANY_GENERIC_AFTER = ("ページ", "メーカー", "業", "現場", "業界", "関係", "画面", "センター", "工事", "機械", "費")

# 様: 仕様・同様・模様・多様・一様・異様・文様 などの一般の語は止めない
_PERSON_SUFFIX_RE = re.compile(
    r"(さん|(?<![仕同模多一異文])様(?![式子々])|(?<![源])氏(?!名)|くん|ちゃん|部長|課長|社長|店長)"
)
_PERSON_GENERIC_BEFORE = {
    "客", "お客", "皆", "担当者", "担当", "利用者", "施主", "業者", "職人", "大工", "先方", "相手", "取引先", "社員",
    "新人", "上司", "部下", "顧客", "会員", "受講者", "参加者", "入居者", "購入者", "依頼者", "発注者", "来場者",
    "来店者", "管理者", "責任者", "応募者", "候補者", "患者", "生徒", "家族", "奥", "子供", "子ども", "営業", "事務",
    "店員", "総務", "経理", "人事", "開発", "製造", "技術", "設計", "工事", "現場", "支店", "本社", "副", "代表取締役",
    "スタッフ", "メンバー", "オーナー", "ユーザー", "ゲスト", "パート", "アルバイト", "業務", "各", "同僚", "元請",
    "下請", "協力会社", "親御", "相談者", "申込者", "契約者", "所有者", "入居", "住人", "近隣", "自社", "他社",
}


def _run_before(t: str, start: int) -> str:
    m = _RUN_RE.search(t[:start])
    return m.group(0) if m else ""


def find_marks(text: str) -> list[str]:
    """当たった印の種類（company_mark・person_mark）。無ければ空。"""
    t = unicodedata.normalize("NFKC", text)
    found: list[str] = []
    if STRONG_COMPANY_RE.search(t):
        found.append("company_mark")
    if "company_mark" not in found:
        for m in _COMPANY_SUFFIX_RE.finditer(t):
            before = _run_before(t, m.start())
            after = t[m.end():]
            if before and before not in _COMPANY_GENERIC_BEFORE and not after.startswith(_COMPANY_GENERIC_AFTER):
                found.append("company_mark")
                break
    for m in _PERSON_SUFFIX_RE.finditer(t):
        before = _run_before(t, m.start())
        if before and before not in _PERSON_GENERIC_BEFORE:
            found.append("person_mark")
            break
    return found
