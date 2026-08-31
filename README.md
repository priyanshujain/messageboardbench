# messageboardbench

Does cheating spread from one AI agent to another through a shared file?

Agents get coding tasks whose tests contradict each other, so no honest solution exists and
any pass is provably a cheat. Each agent also gets a scratch directory the prompt calls
workspace and never describes as a channel. We measure whether carrying that directory from
one agent to the next raises the cheating rate.

Built on [ImpossibleBench](https://github.com/safety-research/impossiblebench) and
[Inspect AI](https://inspect.aisi.org.uk). Tasks and payloads are synthetic throughout.

See `docs/setup.md` to install and run, and `docs/findings.md` for measured numbers.
