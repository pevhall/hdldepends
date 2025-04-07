library ieee;
use ieee.std_logic_1164.all;
use ieee.numeric_std.all;

entity bd_hdl is
  port (
    clk_i : in std_logic;
    src_data_i : in std_logic_vector(31 downto 0);
    dst_data_o : out std_logic_vector(31 downto 0)
  );
end entity;

architecture rtl of bd_hdl is

begin

  process(clk_i)
  begin
    if rising_edge(clk_i) then
      dst_data_o <= not src_data_i;
    end if;
  end process;

end architecture;
