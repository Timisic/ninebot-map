#!/bin/bash
set -uo pipefail
cd "$(dirname "$0")"
./run start
result=$?
if [[ $result -eq 2 ]]; then
  printf '\n已保存可获取的数据，完整性报告中还有缺口或待核实项。\n'
elif [[ $result -ne 0 ]]; then
  printf '\n本次未全部完成，请保留上面的提示。\n'
fi
read -r -p "按回车关闭窗口。" _
exit "$result"
