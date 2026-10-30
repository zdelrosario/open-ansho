from openansho import text_offsets

TEXT = "a😀b😀😀c"  # Qt positions: a=0, 😀=1-2, b=3, 😀=4-5, 😀=6-7, c=8


def test_positions_round_trip():
    for index in range(len(TEXT) + 1):
        position = text_offsets.to_qt_position(TEXT, index)
        assert text_offsets.from_qt_position(TEXT, position) == index
    assert [text_offsets.to_qt_position(TEXT, i) for i in range(len(TEXT) + 1)] == [
        0, 1, 3, 4, 6, 8, 9
    ]


def test_position_inside_a_surrogate_pair_rounds_down():
    assert text_offsets.from_qt_position(TEXT, 2) == 1


def test_qt_slice():
    assert text_offsets.qt_slice(TEXT, 3, 4) == "b"
    assert text_offsets.qt_slice(TEXT, 4, 9) == "😀😀c"
    assert text_offsets.qt_slice("plain text", 0, 5) == "plain"
