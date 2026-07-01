@echo off
rem Bash-free launcher for the nervepack MCP server (stdio) on Windows with no
rem Git for Windows installed. Spawns the server directly via native Python — no
rem bash anywhere. The server resolves toggles/content, matches recall, runs the
rem doctor/toggle/sync/capture/evaluate tools in-process (NP_MCP_PURE_PYTHON is on
rem by default); the two tools that still need bash (flush/maintain) refuse cleanly.
rem
rem Use this .cmd as the MCP "command" on a host without Git-bash; on a host that
rem has Git-bash, use the POSIX `nervepack-mcp` launcher instead (it also pins
rem NP_BASH so the not-yet-ported tools can shell out).
rem
rem %~dp0 is this file's directory (with a trailing backslash).
python "%~dp0..\setup\np-mcp-server.py" %*
