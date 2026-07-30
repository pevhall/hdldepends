library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

use work.counter_pkg.all;

entity counter is
  port (
    clk : in  std_logic;
    rst : in  std_logic;
    q   : out std_logic_vector(WIDTH - 1 downto 0)
  );
end entity counter;

architecture rtl of counter is
  signal cnt : unsigned(WIDTH - 1 downto 0);
begin
  process (clk)
  begin
    if rising_edge(clk) then
      if rst = '1' then
        cnt <= (others => '0');
      else
        cnt <= cnt + 1;
      end if;
    end if;
  end process;

  q <= std_logic_vector(cnt);
end architecture rtl;
