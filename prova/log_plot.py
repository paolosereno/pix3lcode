import numpy as np
import matplotlib.pyplot as plt

# Generate x values from 0.1 to 100 (avoiding log(0))
x = np.linspace(0.1, 100, 1000)

# Calculate natural logarithm of x
y = np.log10(x)

# Create the plot
plt.figure(figsize=(10, 6))
plt.plot(x, y, label='log₁₀(x)')
plt.xlabel('x')
plt.ylabel('log₁₀(x)')
plt.title('Logarithm Base 10 Function')
plt.grid(True)
plt.legend()
plt.show()