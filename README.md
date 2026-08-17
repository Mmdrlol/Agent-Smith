*This activity has been created as part of the 42 curriculum by julhuang*

## Description
This activity consist of creating an llm that can send python code within a
sandbox, explore files using a mcp server and then iterate over the answer of
the sandbox to fix bugs for swe-bench or write functions for mbpp.

## Instructions
After dumping a task from the moulinette (commands in the moulinette's readme),
some default commands are provided with the Makefile such as `make mbpp` for
mbpp tasks or `make swebench` for swe-bench tasks. `make sandbox` also
launches the sandbox with the mcp server in stdio.
Otherwise, the available commands are:
`uv run python -m agent_mbpp ...`
`uv run python -m agent_swebench ...`
`uv run python -m sandbox ...`

## Resources
I did a bunch of online researches because a lot of python concepts wasn't
familiar to me, such as async and pipes. However, this time, I used an llm to
help me understand how to set up docker inside python, as well as how to use
the api, and help me with some parts of the code. I also used it to help me
write the prompt for the llm, but when it comes to the code, everything has
been written by me.

## System architecture
My code is composed of different modules managing different part of the system,
such as the llm, the sandbox, the mcp server and the benchmark tests for mbpp
and swe-bench.

## Agent loop explanation
My code follows the Thought -> Code -> Observation loop. I first giv ethe agent
the system prompt as well as the task to acheive, and it then produces an
answer that is then parsed and feeded into the sandbox and potentially the
mcp server, then the answer of the sandbox is captured and given as a user
message to the llm again.


## Sandbox design
My sandbox is just a seperate process that is executing the provided code using
exec, and all most of the security implementations simply comes from a custom
namespace I created to limit the imports, builtins and files access.
Networking and memory restrictions are directly done on the sandbox process
all together, and timeout is controled by the parent process, that shutdown
the child process is the max time is reached.


## Tool implementation details
Tools are implemented inside the mcp server and then exposed as python
functions inside the sandbox. The manual for all available tools is dynamically
created based on information received by the mcp server. Finally, a lot of
tools have been desabled for mbpp and `run_test` as been overwritten for
swe-bench to execute the `eval_script` inside the docker container.


## Benchmark results and analysis
The benchmark I did on swe-bench tasks shows that qwen3.6-27b was actually more
efficient for swe-tasks than gpt-oss-120b. The reason is that on swe-bench,
I couldn't manage to stop gpt-oss-120b from hallucinating Observations, making
tons of assumptions and outputing way long answers, no matter what I tried in
the system prompt, and even though it still does manage to recalibrate itself
at the end, it end up being way less efficient than qwen3.6-27b which was way
more direct and simplistic. gpt-oss-120b is still really good for mbpp tasks
so I kept it for this benchmark.
