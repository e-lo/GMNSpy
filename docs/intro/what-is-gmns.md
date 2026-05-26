---
title: What is GMNS?
audience: both
kind: concept
summary: Plain-English introduction to the General Modeling Network Specification — what it is, who maintains it, what tables it defines, why a Python toolkit matters.
---

# What is GMNS?

!!! info "Stub — to be filled in Wave 4"
    This page is scaffolded. The content fill is tracked in [issue #96](https://github.com/e-lo/GMNSpy/issues/96) and follows the [Page Style Guide](../_page-style-guide.md).

## What it is

The [General Modeling Network Specification (GMNS)](https://github.com/zephyr-data-specs/GMNS) is the Zephyr Foundation's open standard for representing routable transportation networks in tabular form. It defines a small set of files (`link`, `node`, `geometry`, `lane`, `link_tod`, …) and how they relate via foreign keys.

## Why we have it

(Plain-English paragraph: pre-GMNS, every model used its own network format; GMNS lets a network produced for one model travel to another with zero conversion code.)

## Mental model

(2-3 bullet summary + a single mermaid ER diagram of link → node → lane → link_tod.)

## How it relates to ...

* The Frictionless Data Package format
* GTFS (separate spec, GMNS+GTFS bridging via [openmobilitydata](https://openmobilitydata.org))
* OpenStreetMap

## See also

* [Quickstart](quickstart.md)
* [Visual tour](visual-tour.md)
* [Reference: schema](../reference/spec.md)
