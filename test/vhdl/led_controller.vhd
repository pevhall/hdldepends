library IEEE;
use IEEE.STD_LOGIC_1164.ALL;
use IEEE.NUMERIC_STD.ALL;

entity led_controller is
    Port (
        clk     : in  STD_LOGIC;
        btn     : in  STD_LOGIC_VECTOR(1 downto 0);
        led     : out STD_LOGIC_VECTOR(3 downto 0)
    );
end led_controller;

architecture Behavioral of led_controller is
    -- Simple counter for LED patterns
    signal counter : unsigned(24 downto 0) := (others => '0');
begin
    -- Process to handle the LEDs based on buttons and clock
    process(clk)
    begin
        if rising_edge(clk) then
            -- Increment counter
            counter <= counter + 1;
           
            -- Simple logic:
            -- LED[0] and LED[1] directly mirror BTN[0] and BTN[1]
            led(0) <= btn(0);
            led(1) <= btn(1);
           
            -- LED[2] and LED[3] blink at different rates
            led(2) <= counter(24);  -- Slow blink
            led(3) <= counter(23);  -- Slightly faster blink
        end if;
    end process;
   
end Behavioral;
