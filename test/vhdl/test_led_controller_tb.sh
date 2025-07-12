check_file() {
  if [ -f "$1" ]; then
    return 0  # File exists
  else
    return 1  # File does not exist
  fi
}

rm hdl_deps_led_controller_tb.pickle
hdldepends hdl_deps_led_controller_tb.toml --top-entity led_controller_tb --compile-order-vhdl-lib work:led_controller_tb_compile_order.txt -vvv

check_file "led_controller_tb_compile_order.txt"
if [ $? -eq 0 ]; then
    exit 0
else
    exit 1
fi