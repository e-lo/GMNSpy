"""Generic data-quality rule framework.

Provides: ``Rule`` base class, threshold/config model, entry-point plugin
discovery, ``Issue`` emission with ``category='data_quality'``, and a
``run()`` orchestrator.

Ships **no** domain rules itself — those live in consumer packages
(e.g. ``gmnspy.quality`` registers GMNS-specific rules via entry point).
"""
