# Third-party notices

job-hunter includes or adapts these works. Each keeps its own license.

## humanizer

`skills/job-hunter/references/humanizer.md` is the humanizer skill, version 3.1.0, by Siqi Chen
(https://github.com/blader/humanizer), included unchanged apart from a note at the top. MIT
License; the full text is in `skills/job-hunter/references/humanizer-LICENSE.txt`. Its patterns
come from Wikipedia's "Signs of AI writing" (WikiProject AI Cleanup).

## stop-slop

Phrase lists in `jobhunter/humanize.py` (throat-clearing openers, emphasis crutches, filler,
business jargon, intensifiers) and the five-score check in
`skills/job-hunter/references/review-rubric.md` are adapted from stop-slop by Hardik Pandya
(https://github.com/hardikpandya/stop-slop).

    MIT License

    Copyright (c) 2025 Hardik Pandya

    Permission is hereby granted, free of charge, to any person obtaining a copy
    of this software and associated documentation files (the "Software"), to deal
    in the Software without restriction, including without limitation the rights
    to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
    copies of the Software, and to permit persons to whom the Software is
    furnished to do so, subject to the following conditions:

    The above copyright notice and this permission notice shall be included in all
    copies or substantial portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
    FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
    AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
    LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
    OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
    SOFTWARE.

## slop-guard

`jobhunter/vendor/slop_guard/` is the scoring engine of slop-guard 0.5.0 (commit 7ef2113) by Eric
Tramel (https://github.com/eric-tramel/slop-guard), MIT License (full text in
`jobhunter/vendor/slop_guard/LICENSE`). The command-line and MCP parts are left out; the small
changes made to it are listed in `jobhunter/vendor/README.md`.

## Others

- Occupation data: O*NET 31.0 Database subset, CC BY 4.0 (see `jobhunter/data/README.md`).
- Careers-site directory: downloaded at run time from the ats-scrapers project (MIT), not bundled.
- Font: Atkinson Hyperlegible, SIL Open Font License (`jobhunter/web/static/fonts/OFL.txt`).
