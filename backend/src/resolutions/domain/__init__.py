"""Pure domain layer.

Nothing in this package may import a third-party library, touch the filesystem,
or reach the network. That constraint is what keeps the grouping rules testable
in microseconds and portable to another runtime if throughput ever demands it.
"""
