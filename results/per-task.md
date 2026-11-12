
### Task 1: per-feed fetch interval

| Arm | Correct | Context at finish (median; range) | Cumulative input (median) | Files opened (median; range) | Lines read (median) | Tool calls (median) | check() (median) | Diff files (median; reference 32) | Cost (median) |
|---|---|---|---|---|---|---|---|---|---|
| A0 | 3 of 3 | 58,710; 56,781-69,412 | 396,712 | 11; 10-12 | 1,788 | 67 | 1 | 34 | $1.64 |
| A1 | 3 of 3 | 70,254; 59,479-71,683 | 427,040 | 10; 10-14 | 1,300 | 97 | 1 | 34 | $2.02 |
| B | 3 of 3 | 98,865; 88,222-108,646 | 549,902 | 13; 12-15 | 2,084 | 97 | 1 | 34 | $2.39 |

B and untagged functions (queried / opened per run): 0 / 0, 0 / 0, 0 / 0

Files touched outside the reference set (per run): A0: 2, 2, 2; A1: 1, 2, 2; B: 2, 2, 2

### Task 2: entry word count

| Arm | Correct | Context at finish (median; range) | Cumulative input (median) | Files opened (median; range) | Lines read (median) | Tool calls (median) | check() (median) | Diff files (median; reference 5) | Cost (median) |
|---|---|---|---|---|---|---|---|---|---|
| A0 | 3 of 3 | 37,590; 32,998-38,017 | 194,284 | 6; 6-7 | 1,094 | 33 | 1 | 5 | $0.81 |
| A1 | 3 of 3 | 38,712; 38,408-40,290 | 237,097 | 8; 6-8 | 1,156 | 38 | 1 | 5 | $0.90 |
| B | 3 of 3 | 53,830; 47,831-64,803 | 368,798 | 8; 6-9 | 826 | 33 | 1 | 5 | $1.09 |

B and untagged functions (queried / opened per run): 0 / 4, 1 / 2, 0 / 2

Files touched outside the reference set (per run): A0: 1, 1, 1; A1: 1, 1, 1; B: 1, 1, 0

### Task 3: per-user feed limit

| Arm | Correct | Context at finish (median; range) | Cumulative input (median) | Files opened (median; range) | Lines read (median) | Tool calls (median) | check() (median) | Diff files (median; reference 8) | Cost (median) |
|---|---|---|---|---|---|---|---|---|---|
| A0 | 3 of 3 | 57,290; 47,988-60,039 | 332,119 | 12; 10-13 | 2,062 | 54 | 1 | 10 | $1.45 |
| A1 | 3 of 3 | 62,314; 52,792-64,533 | 331,692 | 10; 9-10 | 1,949 | 48 | 1 | 9 | $1.58 |
| B | 3 of 3 | 81,519; 54,366-85,354 | 489,218 | 11; 9-13 | 1,784 | 50 | 1 | 9 | $1.81 |

B and untagged functions (queried / opened per run): 0 / 0, 0 / 0, 0 / 0

Files touched outside the reference set (per run): A0: 2, 2, 2; A1: 3, 1, 0; B: 0, 2, 1

### Task 4: rotate API keys

| Arm | Correct | Context at finish (median; range) | Cumulative input (median) | Files opened (median; range) | Lines read (median) | Tool calls (median) | check() (median) | Diff files (median; reference 3) | Cost (median) |
|---|---|---|---|---|---|---|---|---|---|
| A0 | 3 of 3 | 19,036; 18,915-20,153 | 102,012 | 4; 4-5 | 294 | 16 | 1 | 4 | $0.44 |
| A1 | 3 of 3 | 18,250; 15,397-21,630 | 86,397 | 4; 4-5 | 473 | 16 | 1 | 4 | $0.43 |
| B | 3 of 3 | 23,892; 18,870-29,104 | 89,164 | 4; 4-5 | 467 | 13 | 1 | 3 | $0.40 |

B and untagged functions (queried / opened per run): 0 / 0, 0 / 0, 0 / 0

Files touched outside the reference set (per run): A0: 1, 1, 1; A1: 0, 1, 1; B: 0, 0, 1

### Task 5: fetch timeout per feed

| Arm | Correct | Context at finish (median; range) | Cumulative input (median) | Files opened (median; range) | Lines read (median) | Tool calls (median) | check() (median) | Diff files (median; reference 8) | Cost (median) |
|---|---|---|---|---|---|---|---|---|---|
| A0 | 3 of 3 | 37,163; 23,885-38,335 | 170,905 | 9; 5-9 | 1,036 | 33 | 1 | 9 | $0.89 |
| A1 | 3 of 3 | 39,606; 35,449-51,045 | 209,599 | 9; 7-10 | 1,141 | 35 | 1 | 9 | $0.96 |
| B | 3 of 3 | 58,453; 55,304-63,049 | 393,801 | 8; 8-8 | 1,464 | 34 | 1 | 7 | $1.17 |

B and untagged functions (queried / opened per run): 0 / 0, 0 / 0, 0 / 0

Files touched outside the reference set (per run): A0: 0, 1, 1; A1: 1, 1, 1; B: 1, 1, 1

### Task 6: audit log

| Arm | Correct | Context at finish (median; range) | Cumulative input (median) | Files opened (median; range) | Lines read (median) | Tool calls (median) | check() (median) | Diff files (median; reference 8) | Cost (median) |
|---|---|---|---|---|---|---|---|---|---|
| A0 | 3 of 3 | 75,189; 39,564-81,296 | 422,321 | 15; 7-16 | 2,646 | 66 | 1 | 12 | $2.11 |
| A1 | 3 of 3 | 81,931; 72,056-93,456 | 490,104 | 15; 15-16 | 2,893 | 71 | 1 | 11 | $2.21 |
| B | 3 of 3 | 60,725; 57,079-83,225 | 365,772 | 13; 12-14 | 1,553 | 71 | 1 | 11 | $1.71 |

Paths found out of 8: A0: 8, 8, 8; A1: 8, 8, 8; B: 8, 8, 8

B and untagged functions (queried / opened per run): 0 / 5, 0 / 1, 0 / 5

Files touched outside the reference set (per run): A0: 5, 0, 8; A1: 6, 6, 3; B: 5, 7, 6

54 runs loaded
