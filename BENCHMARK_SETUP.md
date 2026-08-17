| Model | Solved | Avg iterations | Avg input tokens | Avg time |
| --- | --- | --- | --- | --- |
| openai/gpt-oss-120b | 3/3 | 6.33 | 27982 | 58.5s |
| openai/gpt-oss-20b | 0/3 | 0 | 0 | 0 |
| qwen/qwen3.6-27b | 3/3  | 5 | 13455 | 25.0s |

gpt-oss-20b failed every test because it always tried to call
an internal tool even though they were desabled, resulting
in a BadRequestError 400 from the API.

qwen3.6-27b did spetacularly well, even better than gpt-oss-120b
by a huge margin!! I wasn't expecting this at all, I'm glad
I did this benchmark, it is now the default model for swe-bench
tasks!

The average time is not entirely accurate, because I was
repeatedly hitting RateLimitError 429, slowing me down,
and the test conditions were slightly different between
the models, but it still gives a rough idea of the time
it took.
