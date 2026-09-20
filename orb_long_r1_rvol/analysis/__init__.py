"""Python companion for the ORB Long r1+RVOL Pine indicator (spec Section 9).

Pine is the signal, display, and alert layer (Section 2). This package
cross-checks Pine's own statistics against an independent recomputation,
runs the r1-continuation regression the paper's hypothesis rests on, builds
diagnostic breakdowns, and runs the block-bootstrap prop-challenge Monte
Carlo that Pine cannot do on its own.
"""
