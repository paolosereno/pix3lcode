import numpy as np
import matplotlib.pyplot as plt

# Creare un array di valori da 0 a 100
x = np.linspace(0, 100, 1000)

# Calcolare la radice quadrata di ogni valore
y = np.sqrt(x)

# Creare il grafico
plt.figure(figsize=(10, 6))
plt.plot(x, y, label='f(x) = √x', color='blue')
plt.title('Grafico della Radice Quadrata')
plt.xlabel('x')
plt.ylabel('√x')
plt.grid(True, alpha=0.3)
plt.legend()
plt.xlim(0, 100)
plt.ylim(0, 10)

# Salvare il grafico come file immagine
plt.tight_layout()
plt.savefig('square_root_plot.png', dpi=300, bbox_inches='tight')
print("Grafico salvato come 'square_root_plot.png'")

# Mostrare un messaggio se si vuole visualizzarlo
print("Per visualizzare il grafico, apri il file 'square_root_plot.png'")