library ieee;
use ieee.std_logic_1164.all;

-- Simulation-only testbench. It is deliberately NOT listed in hdldeps.yaml;
-- analyse_example.py adds it on the fly via `top_file`, showing that a
-- testbench top level need not be in the config to get a compile order.
entity counter_tb is
end entity counter_tb;

architecture sim of counter_tb is
  signal clk : std_logic := '0';
  signal rst : std_logic := '1';
  signal q   : std_logic_vector(7 downto 0);
begin
  dut : entity work.counter
    port map (
      clk => clk,
      rst => rst,
      q   => q
    );

  clk <= not clk after 5 ns;
  rst <= '0' after 20 ns;
end architecture sim;
