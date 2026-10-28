# Bundled data

## occupations.json.gz

A subset of the **O\*NET® 31.0 Database** by the U.S. Department of Labor, Employment and
Training Administration (USDOL/ETA), used under the
[CC BY 4.0 license](https://creativecommons.org/licenses/by/4.0/). O\*NET® is a trademark of
USDOL/ETA.

job-hunter has modified all or some of this information. USDOL/ETA has not approved, endorsed,
or tested these modifications. Changes: only these fields were kept, from these files of the
text release: occupation titles (Occupation Data), job zones (Job Zones), primary related
occupations (Related Occupations, top 10), in-demand and hot-technology software (Software
Skills, top 12), knowledge areas with importance 3.0+ (Knowledge, top 6), up to 6 reported
titles per occupation (Sample of Reported Titles), and an index of normalized job titles from
Occupation Data, Sample of Reported Titles and Job Titles. `scripts/build_occupations.py` is
the exact transformation; rerun it on a newer release to update.

Source: https://www.onetcenter.org/database.html
