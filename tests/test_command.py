from commands import AddSub, DeleteSub, Help, ListSubs, parse_command

URL = "https://rent.591.com.tw/list?region=1&section=5"


def test_url_with_name_splits_both():
    result = parse_command(f"中山區套房 {URL}")
    assert isinstance(result, AddSub)
    assert result.name == "中山區套房"
    assert result.url == URL


def test_name_after_url_also_works():
    result = parse_command(f"{URL} 中山區套房")
    assert isinstance(result, AddSub)
    assert result.name == "中山區套房"


def test_bare_url_has_empty_name():
    # 名稱留空，由呼叫端依現有訂閱數量命名為「條件 N」
    result = parse_command(URL)
    assert isinstance(result, AddSub)
    assert result.name == ""
    assert result.url == URL


def test_url_with_newline_separated_name():
    result = parse_command(f"中山區套房\n{URL}")
    assert isinstance(result, AddSub)
    assert result.name == "中山區套房"


def test_foreign_url_is_not_add():
    # 非 591 網域不當成新增指令，落到 Help
    assert isinstance(parse_command("https://evil.example.com/list"), Help)


def test_detail_page_url_is_not_add():
    # 物件詳情頁不是搜尋條件
    assert isinstance(parse_command("https://rent.591.com.tw/21977665"), Help)


def test_list_command_chinese():
    assert isinstance(parse_command("清單"), ListSubs)


def test_list_command_english_and_whitespace():
    assert isinstance(parse_command("  list  "), ListSubs)


def test_delete_command_chinese():
    result = parse_command("刪除 2")
    assert isinstance(result, DeleteSub)
    assert result.index == 2


def test_delete_command_without_space():
    result = parse_command("刪除2")
    assert isinstance(result, DeleteSub)
    assert result.index == 2


def test_delete_command_english():
    result = parse_command("del 3")
    assert isinstance(result, DeleteSub)
    assert result.index == 3


def test_delete_without_number_is_help():
    assert isinstance(parse_command("刪除"), Help)


def test_gibberish_is_help():
    assert isinstance(parse_command("你好嗎"), Help)


def test_empty_is_help():
    assert isinstance(parse_command("   "), Help)


def test_fullwidth_comma_does_not_get_swallowed_into_url():
    # 中文輸入最常見的寫法：網址後直接接全形逗號，不留空格。
    # 若正則吃掉全形標點，整段中文會被併進網址，條件靜默損毀。
    result = parse_command(f"{URL}，大安套房不錯")
    assert isinstance(result, AddSub)
    assert result.url == URL
    assert result.name == "大安套房不錯"


def test_fullwidth_period_is_stripped_from_url():
    result = parse_command(f"{URL}。")
    assert isinstance(result, AddSub)
    assert result.url == URL
    assert result.name == ""


def test_halfwidth_comma_inside_query_is_preserved():
    # 591 的 section=5,7 用半形逗號表示多選鄉鎮區，絕不能被當成句尾標點剝掉
    url_with_comma = "https://rent.591.com.tw/list?region=1&section=5,7"
    result = parse_command(f"中山區套房 {url_with_comma}")
    assert isinstance(result, AddSub)
    assert result.url == url_with_comma
    assert result.name == "中山區套房"


def test_second_url_does_not_leak_into_name():
    result = parse_command(f"看 {URL} 和 https://rent.591.com.tw/list?region=2")
    assert isinstance(result, AddSub)
    assert result.url == URL
    assert result.name == ""


def test_name_whitespace_is_normalised():
    # 把網址從訊息中間挖掉會留下連續空白
    result = parse_command(f"大安區 {URL}, 備註")
    assert isinstance(result, AddSub)
    assert result.name == "大安區 備註"
