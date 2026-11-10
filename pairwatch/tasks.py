"""Built-in C++ pair-programming tasks, each with stdin -> stdout tests.

Teachers can add their own tasks in Documents/PairWatch/tasks.json (same fields).
Tasks go from warm-up to harder, so pairs of different levels all solve something.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

STARTER = """#include <iostream>
using namespace std;

int main() {
    // read the input, solve, print the answer

    return 0;
}
"""


@dataclass
class Task:
    id: str
    title: str
    text: str
    tests: list[tuple[str, str]]          # (stdin, expected stdout)
    starter: str = STARTER
    level: int = 1
    solution: str = field(default="", repr=False)  # reference solution (used by self-tests)


TASKS: list[Task] = [
    Task("digits", "Sum of digits",
         "Read a non-negative integer n (up to 10^18). Print the sum of its digits.\n\n"
         "Example: input 4096 -> output 19",
         [("4096\n", "19"), ("0\n", "0"), ("7\n", "7"), ("999999999999999999\n", "162")], level=1,
         solution="""#include <iostream>
#include <string>
using namespace std;
int main(){ string s; cin>>s; int t=0; for(char c: s) t+=c-'0'; cout<<t; }"""),
    Task("palindrome", "Palindrome check",
         "Read one word (only lowercase letters). Print YES if it reads the same backwards, otherwise NO.\n\n"
         "Example: input level -> output YES",
         [("level\n", "YES"), ("pair\n", "NO"), ("a\n", "YES"), ("abba\n", "YES"), ("abca\n", "NO")], level=1,
         solution="""#include <iostream>
#include <string>
using namespace std;
int main(){ string s; cin>>s; string r(s.rbegin(), s.rend()); cout<<(s==r?"YES":"NO"); }"""),
    Task("second", "Second largest",
         "The first line has n (2 <= n <= 1000). The second line has n integers.\n"
         "Print the second largest DIFFERENT value. If all values are equal, print NONE.\n\n"
         "Example: input 5 / 4 9 2 9 7 -> output 7",
         [("5\n4 9 2 9 7\n", "7"), ("3\n5 5 5\n", "NONE"), ("2\n-1 -3\n", "-3"), ("4\n1 2 3 4\n", "3")], level=2,
         solution="""#include <iostream>
#include <climits>
using namespace std;
int main(){ int n; cin>>n; long long a=LLONG_MIN,b=LLONG_MIN; for(int i=0;i<n;i++){ long long x; cin>>x;
 if(x>a){ b=a; a=x; } else if(x<a && x>b) b=x; } if(b==LLONG_MIN) cout<<"NONE"; else cout<<b; }"""),
    Task("primes", "Primes in a range",
         "Read two integers a and b (1 <= a <= b <= 100000). Print how many prime numbers lie between a and b, inclusive.\n\n"
         "Example: input 1 10 -> output 4   (2, 3, 5, 7)",
         [("1 10\n", "4"), ("10 20\n", "4"), ("1 1\n", "0"), ("1 100000\n", "9592"), ("97 97\n", "1")], level=2,
         solution="""#include <iostream>
#include <vector>
using namespace std;
int main(){ int a,b; cin>>a>>b; vector<bool> p(b+1,true); p[0]=false; if(b>=1) p[1]=false;
 for(int i=2;(long long)i*i<=b;i++) if(p[i]) for(int j=i*i;j<=b;j+=i) p[j]=false;
 int c=0; for(int i=a;i<=b;i++) c+=p[i]; cout<<c; }"""),
    Task("brackets", "Balanced brackets",
         "Read one line containing only the characters ( ) [ ] { }. Print YES if every bracket is closed in the right order, otherwise NO.\n\n"
         "Example: input ([]{}) -> output YES;  input ([)] -> output NO",
         [("([]{})\n", "YES"), ("([)]\n", "NO"), ("((\n", "NO"), ("{[()()]}\n", "YES"), (")(\n", "NO")], level=3,
         solution="""#include <iostream>
#include <string>
#include <stack>
using namespace std;
int main(){ string s; cin>>s; stack<char> st; for(char c: s){ if(c=='('||c=='['||c=='{') st.push(c); else {
 if(st.empty()){ cout<<"NO"; return 0; } char o=st.top(); st.pop();
 if((c==')'&&o!='(')||(c==']'&&o!='[')||(c=='}'&&o!='{')){ cout<<"NO"; return 0; } } }
 cout<<(st.empty()?"YES":"NO"); }"""),
    Task("spiral", "Matrix in a spiral",
         "The first line has r and c (1 <= r, c <= 20). Then r lines with c integers each.\n"
         "Print all values in clockwise spiral order, starting at the top-left, separated by spaces.\n\n"
         "Example: 3 3 / 1 2 3 / 4 5 6 / 7 8 9 -> 1 2 3 6 9 8 7 4 5",
         [("3 3\n1 2 3\n4 5 6\n7 8 9\n", "1 2 3 6 9 8 7 4 5"), ("1 4\n1 2 3 4\n", "1 2 3 4"),
          ("3 1\n1\n2\n3\n", "1 2 3"), ("2 3\n1 2 3\n4 5 6\n", "1 2 3 6 5 4")], level=3,
         solution="""#include <iostream>
#include <vector>
using namespace std;
int main(){ int r,c; cin>>r>>c; vector<vector<int>> m(r, vector<int>(c)); for(auto&row:m) for(auto&x:row) cin>>x;
 int t=0,b=r-1,l=0,rt=c-1; bool first=true; auto out=[&](int v){ if(!first) cout<<' '; cout<<v; first=false; };
 while(t<=b && l<=rt){ for(int j=l;j<=rt;j++) out(m[t][j]); t++; for(int i=t;i<=b;i++) out(m[i][rt]); rt--;
  if(t<=b){ for(int j=rt;j>=l;j--) out(m[b][j]); b--; } if(l<=rt){ for(int i=b;i>=t;i--) out(m[i][l]); l++; } } }"""),
]


def load_tasks(custom: Path | None = None) -> list[Task]:
    """Built-in tasks, then any teacher tasks from a JSON file:
    [{"id": "...", "title": "...", "text": "...", "tests": [["input", "output"], ...], "level": 1}]"""
    tasks = list(TASKS)
    if custom and custom.exists():
        try:
            for d in json.loads(custom.read_text(encoding="utf-8")):
                tasks.append(Task(d["id"], d["title"], d["text"], [tuple(t) for t in d["tests"]],
                                  d.get("starter", STARTER), int(d.get("level", 1))))
        except (ValueError, KeyError, TypeError):
            pass  # a broken custom file should not stop the class
    return tasks
