"""`dicom.convert` (DICOM_CONVERTER.md, ADR-0017): scan → select (analyzers) → convert → emit.

Ported from the owner's converter (reference only, `legacy/convert/`, R9). Plugins never import
`app`; the task talks to the backend through the run protocol (`plugins/protocol.py`).
"""
