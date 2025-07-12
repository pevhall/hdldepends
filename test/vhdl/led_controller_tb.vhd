
library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity led_controller_tb is
end;

architecture bench of led_controller_tb is
  constant clk_period : time := 1 ns;
  signal clk : std_logic                    := '1';
  signal btn : std_logic_vector(1 downto 0) := (others => '0');
  signal led : std_logic_vector(3 downto 0);
begin

  i_led_controller : entity work.led_controller
    port map
    (
      clk => clk,
      btn => btn,
      led => led
    );
  clk <= not clk after clk_period/2;

end;