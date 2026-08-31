"""Horizontal pager animation, drag and edge resistance."""

from deskcamdio.ui.pager import PagePager


def test_programmatic_move_animates_then_commits() -> None:
    pager = PagePager(3)
    assert pager.move(1)
    pager.update(0.1)
    assert pager.index == 0
    assert -480 < pager.offset < 0
    assert pager.visible_pages() == (0, 1)
    pager.update(0.3)
    assert pager.index == 1
    assert pager.offset == 0


def test_animation_uses_fast_then_soft_nonlinear_motion() -> None:
    pager = PagePager(2)
    assert pager.move(1)
    pager.update(0.08)
    first_step = abs(pager.offset)
    pager.update(0.08)
    second_step = abs(pager.offset) - first_step
    assert first_step > second_step > 0


def test_drag_is_followed_and_uses_boundary_resistance() -> None:
    pager = PagePager(2)
    pager.begin_drag(100, now=0.0)
    pager.drag_to(200, now=0.1)
    assert 0 < pager.offset < 100  # first-page right edge is elastic
    first_pull = pager.offset
    pager.drag_to(300, now=0.2)
    assert pager.offset - first_pull < first_pull  # resistance increases non-linearly
    assert pager.end_drag(300, now=0.3)
    pager.update(0.3)
    assert pager.index == 0

    pager.begin_drag(300, now=1.0)
    pager.drag_to(100, now=1.1)
    assert pager.offset == -200
    assert pager.end_drag(100, now=1.2)
    pager.update(0.3)
    assert pager.index == 1
